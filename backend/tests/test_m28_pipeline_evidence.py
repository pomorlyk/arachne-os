from types import SimpleNamespace

import pytest

from config import load_settings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.particles import ParticleEngine
from core.schemas import CapabilityBall, UnitSlot
from swarm.skill_pipeline_composer import SkillPipelineComposer


@pytest.fixture
def composer(tmp_path):
    settings = load_settings(llm_api_key='', vault_storage_dir=tmp_path / 'vault',
                             sandbox_workspace_dir=tmp_path / 'sandbox',
                             sqlite_db_url=f'sqlite+aiosqlite:///{tmp_path}/test.db')
    vault = BlackBoxVault(settings.vault_storage_dir)
    particles = ParticleEngine(vault)
    for bid in ('BALL_DATA_BULK_DISCOUNT_MATRIX', 'BALL_DATA_SHIPPING_RULE_DOC', 'BALL_SKILL_ORDER_CHECKLIST'):
        particles.register_ball(CapabilityBall(ball_id=bid, ball_type='DATA', title=bid,
                                               content='Reference only', owner_slot_ids=[]))
    containers = ContainerRegistry()
    containers._slots['SLOT_TEST'] = UnitSlot(slot_id='SLOT_TEST', slot_name='test', occupant_id='creator')
    return SkillPipelineComposer(SimpleNamespace(settings=settings, vault=vault,
                                  particles=particles, containers=containers))


def test_template_is_unvalidated_candidate_unmounted(composer):
    result = composer.compose_and_verify_pipeline(preset_id='pipe_end_to_end_order_profit', target_slot_id='SLOT_TEST')
    assert result['master_ball']['status'] == 'CANDIDATE'
    assert result['mounted_to_slot_id'] is None
    assert result['validation_status'] == 'UNVALIDATED'
    assert result['evidence_provenance']['implementation'] == 'PRESET_TEMPLATE'
    assert result['evidence_provenance']['source_code_executed'] is False
    assert result['sandbox_verification']['process_passed'] is True
    assert result['sandbox_verification']['passed'] is False
    assert not composer._state.containers.get_slot('SLOT_TEST').ball_ids
    assert all(stage['source_ball_id'] is None for stage in result['stage_breakdown'])
    assert all('content' not in source and 'code_excerpt' not in source for source in result['source_balls'])


@pytest.mark.parametrize('source', ['MISSING', 'BALL_DATA_BULK_DISCOUNT_MATRIX'])
def test_missing_or_inactive_source_is_rejected(composer, source):
    if source != 'MISSING':
        composer._state.particles.get_ball(source).status = 'CANDIDATE'
    with pytest.raises(ValueError, match='source|Source'):
        composer.compose_and_verify_pipeline(preset_id='pipe_end_to_end_order_profit',
                                            source_skill_ball_ids=[source, "BALL_DATA_SHIPPING_RULE_DOC", "BALL_SKILL_ORDER_CHECKLIST"])
    assert composer.get_history()['composed_count'] == 0


def test_unknown_instructions_do_not_select_profit_template(composer):
    with pytest.raises(ValueError, match='preset'):
        composer.compose_and_verify_pipeline(pipeline_instruction='Translate poetry into French')
    with pytest.raises(ValueError, match='preset'):
        composer.compose_and_verify_pipeline(preset_id='missing')


def test_execution_needs_explicit_sandbox_preview_and_known_pipeline(composer):
    result = composer.compose_and_verify_pipeline(preset_id='pipe_end_to_end_order_profit', target_slot_id='SLOT_TEST')
    with pytest.raises(ValueError, match='sandbox_preview'):
        composer.execute_pipeline(pipeline_id=result['pipeline_id'])
    with pytest.raises(KeyError):
        composer.execute_pipeline(ball_id='BALL_DATA_SHIPPING_RULE_DOC', sandbox_preview=True)
    preview = composer.execute_pipeline(pipeline_id=result['pipeline_id'], sandbox_preview=True)
    assert preview['status'] == 'SANDBOX_ONLY'
    assert preview['execution_evidence']['business_execution_completed'] is False
    assert preview['validation_status'] == 'UNVALIDATED'
    with pytest.raises(KeyError):
        composer.execute_pipeline(pipeline_id='unknown', sandbox_preview=True)


def test_zero_is_preserved_and_invalid_numbers_rejected(composer):
    result = composer.compose_and_verify_pipeline(preset_id='pipe_end_to_end_order_profit', target_slot_id='SLOT_TEST',
                                                test_payload={'quantity': 0, 'unit_price': 0, 'tax_rate': 0, 'weight_kg': 0})
    assert result['final_output']['discounted_amount'] == 0
    assert result['final_output']['tax_amount'] == 0
    for payload in ({'quantity': -1}, {'quantity': float('nan')}, {'unit_price': 'bad'}, {'tax_rate': None}):
        with pytest.raises(ValueError):
            composer.execute_pipeline(pipeline_id=result['pipeline_id'], payload=payload, sandbox_preview=True)


def test_preview_rejects_changed_source(composer):
    result = composer.compose_and_verify_pipeline(preset_id='pipe_end_to_end_order_profit', target_slot_id='SLOT_TEST')
    path = composer.sandbox_dir / result['script_filename']
    path.write_text('def execute_skill(payload):\n    return {"result": 0}\n')
    with pytest.raises(ValueError, match='source changed'):
        composer.execute_pipeline(pipeline_id=result['pipeline_id'], sandbox_preview=True)


def test_pipeline_api_requires_independent_review_and_persists(tmp_path):
    from fastapi.testclient import TestClient
    from main import create_app

    settings = load_settings(llm_api_key='', enforce_bearer_auth=True,
                             vault_storage_dir=tmp_path / 'vault', sandbox_workspace_dir=tmp_path / 'sandbox',
                             sqlite_db_url=f'sqlite+aiosqlite:///{tmp_path}/pipeline.db')
    def login(client, role):
        service = client.app.state.runtime.auth_custody
        account = next(a for a in service.list_public_accounts() if a.role_view == role)
        service.set_password(account.user_id, 'pipeline-test-password')
        token = client.post('/api/v1/auth/login', json={'username': account.user_id, 'password': 'pipeline-test-password'}).json()['token']
        return account, {'Authorization': f'Bearer {token}'}

    with TestClient(create_app(settings)) as client:
        creator, manager_headers = login(client, 'manager')
        reviewer, boss_headers = login(client, 'boss')
        _, employee_headers = login(client, 'employee')
        assert client.post('/api/v1/pipelines/compose', json={'preset_id': 'pipe_end_to_end_order_profit'}, headers=employee_headers).status_code == 403
        composed = client.post('/api/v1/pipelines/compose', json={'preset_id': 'pipe_end_to_end_order_profit'}, headers=manager_headers)
        assert composed.status_code == 200
        data = composed.json()
        assert data['proposer_id'] == creator.user_id
        rt = client.app.state.runtime
        assert rt.particles.get_ball(data['master_ball_id']).status == 'CANDIDATE'
        assert client.post('/api/v1/pipelines/execute', json={'pipeline_id': data['pipeline_id']}, headers=manager_headers).status_code == 400
        assert client.post('/api/v1/pipelines/execute', json={'ball_id': 'BALL_SKILL_ORDER_CHECKLIST', 'sandbox_preview': True}, headers=manager_headers).status_code == 404
        assert client.post('/api/v1/pipelines/compose', json={'preset_id': 'pipe_end_to_end_order_profit', 'source_skill_ball_ids': []}, headers=manager_headers).status_code == 400
        samples = [{'input_payload': {'quantity': q, 'unit_price': 100, 'cost_unit_price': 40, 'weight_kg': 2, 'tax_rate': 0},
                    'expected_output': {'result': expected}}
                   for q, expected in ((1, 50), (2, 110), (3, 170))]
        review = {'approved_source_hash': data['source_hash'], 'independent_samples': samples}
        publish_path = f"/api/v1/evolution/candidates/{data['proposal_id']}/publish"
        assert client.post(publish_path, json=review, headers=manager_headers).status_code == 403
        assert client.post(publish_path, json={**review, 'approved_source_hash': '0' * 64}, headers=boss_headers).status_code == 422
        assert client.post(publish_path, json={**review, 'independent_samples': [samples[0]] * 3}, headers=boss_headers).status_code == 422
        wrong = [{**sample, 'expected_output': {'result': -1}} for sample in samples]
        failed = client.post(publish_path, json={**review, 'independent_samples': wrong}, headers=boss_headers)
        assert failed.status_code == 200
        assert failed.json()['status'] == 'VALIDATION_FAILED'
        assert rt.particles.get_ball(data['master_ball_id']).status == 'CANDIDATE'
        assert data['master_ball_id'] not in rt.containers.get_slot(data['target_slot_id']).ball_ids
        published = client.post(publish_path, json=review, headers=boss_headers)
        assert published.status_code == 200
        assert published.json()['status'] == 'ACTIVE'
        assert data['master_ball_id'] in rt.containers.get_slot(data['target_slot_id']).ball_ids
        assert len(rt.skill_pipeline_composer._composed_pipelines) == 1
        assert rt.vault.verify_chain_integrity().intact

    with TestClient(create_app(settings)) as restored:
        rt = restored.app.state.runtime
        report = next(r for r in rt.arena.list_reports() if r.proposal_id == data['proposal_id'])
        assert report.promoted and report.validation_status == 'INDEPENDENTLY_REVIEWED'
        assert rt.particles.get_ball(data['master_ball_id']).status == 'ACTIVE'
        assert data['master_ball_id'] in rt.containers.get_slot(data['target_slot_id']).ball_ids
        assert len(rt.skill_pipeline_composer._composed_pipelines) == 1

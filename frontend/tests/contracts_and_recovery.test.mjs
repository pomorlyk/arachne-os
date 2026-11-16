import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const entry = path.join(root, ".tmp_contract_entry.ts");
const bundle = path.join(root, ".tmp_contract_bundle.mjs");
fs.writeFileSync(entry, 'export * from "./src/api"; export * from "./src/sessionTransport"; export * from "./src/components/AutonomousCommandStudioModal"; export {App} from "./src/App"; export {DaySimulationTimeline} from "./src/components/DaySimulationTimeline"; export {CandidateReview} from "./src/components/CandidateReview"; export {ShadowOutputReviews} from "./src/components/ShadowOutputReviews"; export {renderToStaticMarkup} from "react-dom/server"; export {createElement} from "react";');
execFileSync(path.join(root, "node_modules/.bin/esbuild"), [entry, "--bundle", "--platform=node", "--format=esm", "--external:react", "--external:react-dom", "--loader:.css=empty", "--banner:js=import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);", `--outfile=${bundle}`, '--define:import.meta.env={"VITE_API_BASE_URL":"https://enterprise.example"}'], { stdio: "pipe" });
const api = await import(pathToFileURL(bundle).href);
const originalFetch = globalThis.fetch;
const wait = (ms = 10) => new Promise(resolve => setTimeout(resolve, ms));
const json = (value, status = 200) => new Response(JSON.stringify(value), { status });
test.after(() => { globalThis.fetch = originalFetch; api.setStoredAuthToken(null); fs.unlinkSync(entry); fs.unlinkSync(bundle); });
test.afterEach(() => { globalThis.fetch = originalFetch; api.setStoredAuthToken(null); });

test("all advanced studio helpers send current Bearer credential and canonical wargame false", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push({url, init}); return json({ run_id: "RUN-1", scope: { isolated: true }, monte_carlo_metrics: {survival_score: 12, p10_net_cashflow_impact: -900}, timeline_stages: [{phase: "plan"}], forged_defensive_balls: [] }); };
  api.setStoredAuthToken("real-current-token");
  await api.apiFetchWargameScenarios();
  const result = await api.apiRunWargameSimulation({scenario_id_or_custom: "CUSTOM", custom_title: "tail risk", custom_description: "scenario", horizon_days: 30, monte_carlo_paths: 20, auto_forge_defensive_balls: false});
  await api.apiDistillSlotMemory({slot_id: "S1", auto_upgrade_balls: false});
  await api.apiExecuteZeroLossHandover({slot_id: "S1", new_occupant_name: "Person"});
  await api.apiFetchMemoryCrystals("S1");
  await api.apiFetchPipelinePresets();
  await api.apiComposeSkillPipeline({preset_id:"known-preset", pipeline_title: "P", source_skill_ball_ids: ["B"], target_slot_id: "S1", test_payload: {}});
  const pipeline = await api.apiExecuteSkillPipeline({pipeline_id:"PIPE-1", payload: {}, sandbox_preview:true});
  assert.equal(pipeline.executed_ok, false, "missing outcome must not become success");
  for (const call of calls) {
    assert.equal(call.init.headers.Authorization, "Bearer real-current-token");
    assert.match(call.url, /^https:\/\/enterprise\.example\/api\//);
  }
  assert.deepEqual(JSON.parse(calls[1].init.body), {scenario_id_or_custom: "CUSTOM", custom_title: "tail risk", custom_description: "scenario", horizon_days: 30, monte_carlo_paths: 20, auto_forge_defensive_balls: false});
  assert.equal(result.cashflow_distribution.p10_cny, -900);
  assert.equal(result.survival_score, 12);
  assert.equal(Number.isNaN(result.cashflow_distribution.p50_cny), true, "missing model result must not be fabricated");
  assert.equal(result.run_id, "RUN-1");
  assert.deepEqual(result.defense_timeline, [{phase: "plan"}]);
  assert.equal(api.getWebSocketUrl(), "wss://enterprise.example/ws/events");
});

test("missing or expired identity requires login; forbidden and outage preserve identity", async () => {
  const calls = [];
  let invalidations = 0;
  const off = api.onAuthenticationRequired(() => invalidations++);
  globalThis.fetch = async (url) => { calls.push(url); return json({detail: "expired"}, 401); };
  try {
    api.setStoredAuthToken(null);
    await assert.rejects(api.fetchCurrentAccount(), api.AuthenticationError);
    assert.deepEqual(calls, [], "missing token must never trigger login or account fallback");
    api.setStoredAuthToken("expired");
    await assert.rejects(api.fetchCurrentAccount(), api.AuthenticationError);
    assert.equal(api.getStoredAuthToken(), null);
    assert.equal(invalidations, 2);
    assert.equal(calls.length, 1);
    assert.match(calls[0], /\/auth\/me$/);
    for (const status of [403, 503]) {
      api.setStoredAuthToken("retain-identity");
      globalThis.fetch = async () => json({detail: "unavailable"}, status);
      await assert.rejects(api.fetchCurrentAccount(), error => error.status === status && !(error instanceof api.AuthenticationError));
      assert.equal(api.getStoredAuthToken(), "retain-identity");
    }
  } finally { off(); }
});

test("login uses verified /me metadata instead of login or cached account", async () => {
  globalThis.fetch = async url => String(url).endsWith("/auth/login")
    ? json({ token: "verified-token", account: {user_id: "wrong-login-profile"} })
    : json({ account: {user_id: "actual-user", role_view: "employee"} });
  const result = await api.loginAccount("selected-user", "entered-password");
  assert.equal(result.account.user_id, "actual-user");
});

test("an old 401 or logout response cannot erase a newer login", async () => {
  let resolve;
  globalThis.fetch = () => new Promise(done => { resolve = done; });
  api.setStoredAuthToken("old");
  const pending = api.fetchCurrentAccount();
  api.setStoredAuthToken("new");
  resolve(json({detail:"expired"}, 401));
  await assert.rejects(pending, api.AuthenticationError);
  assert.equal(api.getStoredAuthToken(), "new");
  const logout = api.logoutAccount();
  api.setStoredAuthToken("newer");
  resolve(json({ok:true}));
  await logout;
  assert.equal(api.getStoredAuthToken(), "newer");
});

test("WS authenticates by first frame, waits for ack, stops on logout and bounds reconnect", async () => {
  const sockets = [];
  const states = [];
  let events = 0;
  const createSocket = url => {
    const socket = { url, sent: [], close() { this.onclose?.({code:1000}); }, send(frame) { this.sent.push(JSON.parse(frame)); } };
    sockets.push(socket); return socket;
  };
  api.setStoredAuthToken("ws-secret");
  const dispose = api.connectAuthenticatedEvents(state => states.push(state), () => events++, {createSocket, retryDelayMs:1, maxRetries:2});
  assert.equal(sockets[0].url.includes("ws-secret"), false);
  sockets[0].onopen();
  assert.deepEqual(sockets[0].sent, [{type:"authenticate",token:"ws-secret"}]);
  assert.equal(states.at(-1), false);
  sockets[0].onmessage({data:JSON.stringify({type:"pulse"})});
  assert.equal(events, 0);
  sockets[0].onmessage({data:JSON.stringify({type:"authenticated"})});
  assert.equal(states.at(-1), true);
  sockets[0].onmessage({data:JSON.stringify({type:"pulse"})});
  assert.equal(events, 1);
  sockets[0].close(); await wait(); sockets[1].close(); await wait(); sockets[2].close(); await wait();
  assert.equal(sockets.length, 3);
  dispose();
  api.setStoredAuthToken("fresh");
  const stop = api.connectAuthenticatedEvents(() => {}, () => events++, {createSocket, retryDelayMs:1});
  const last = sockets.at(-1);
  api.setStoredAuthToken(null); last.close(); await wait();
  assert.equal(sockets.at(-1), last, "logout prevents reconnect");
  stop();
});

test("refresh pulse bursts coalesce and only one followup runs after an in-flight request", async () => {
  let resolve;
  let calls = 0;
  const scheduler = api.createRefreshScheduler(async () => { calls++; if (calls === 1) await new Promise(done => { resolve = done; }); }, 1);
  for (let index=0; index<30; index++) scheduler.schedule();
  await wait(); assert.equal(calls,1);
  for (let index=0; index<30; index++) scheduler.schedule();
  resolve(); await wait(); assert.equal(calls,2);
  scheduler.schedule(); scheduler.dispose(); await wait(); assert.equal(calls,2);
});

test("candidate publication sends reviewed hash and independent samples through auth", async () => {
  let captured;
  globalThis.fetch = async (url, init) => { captured={url,init}; return json({status:"CANDIDATE", report:{promoted:false}}); };
  api.setStoredAuthToken("reviewer-token");
  const samples = [1,2,3].map(value => ({input_payload:{value}, expected_output:{value}}));
  const result = await api.publishEvolutionCandidate("proposal/id", {reviewer_id:"manager", approved_source_hash:"hash", independent_samples:samples});
  assert.match(captured.url, /proposal%2Fid\/publish$/);
  assert.equal(captured.init.headers.Authorization, "Bearer reviewer-token");
  assert.equal(JSON.parse(captured.init.body).approved_source_hash,"hash");
  assert.equal(result.report.promoted,false);
});


test("cached account metadata cannot bypass the login gate without a token", () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem(key) { return key === "arachne_logged_account_v1" ? JSON.stringify({ user_id: "forged-admin", name: "Forged Administrator", role_view: "boss" }) : null; },
    setItem() {}, removeItem() {},
  } });
  try {
    api.setStoredAuthToken(null);
    const html = api.renderToStaticMarkup(api.createElement(api.App));
    assert.match(html, /账号登录/);
    assert.doesNotMatch(html, /Forged Administrator|经营后台/);
    assert.doesNotMatch(html, /value="123456"/);
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "localStorage", descriptor);
    else delete globalThis.localStorage;
  }
});

test("day rehearsal renders run isolation and actual failure/review counts", () => {
  const html = api.renderToStaticMarkup(api.createElement(api.DaySimulationTimeline, {
    simStatus: { run_id: "RUN-FAIL", status:"PENDING_REVIEW", scope:{isolated:true}, current_time:"09:00", current_index:2, total_stages:3, is_day_completed:false, next_stage:null, schedule:[], completed_logs:[{status:"FAILED",time:"08:30"},{status:"PENDING_REVIEW",time:"09:00"}], metrics:{gmv_cny:0,orders_processed:0,skills_minted:0,redlines_blocked:0,local_rollbacks:0} }, telemetry:null, busyAction:null, onStep:async()=>{}, onRunFullDay:async()=>{}, onResetDay:async()=>{},
  }));
  assert.match(html,/RUN-FAIL/);
  assert.match(html,/已隔离/);
  assert.match(html,/失败 1/);
  assert.match(html,/待复核 1/);
  assert.match(html,/不代表实际经营业绩/);
});

test("unpublished candidate renders explicit pending state and hash review", () => {
  const html = api.renderToStaticMarkup(api.createElement(api.CandidateReview, { report:{proposal_id:"P1",promoted:false,source_hash:"source-digest",candidate_status:"CANDIDATE",validation_status:"SYNTHETIC_ONLY"}, reviewerId:"manager" }));
  assert.match(html,/候选技能尚未挂载/);
  assert.match(html,/source-digest/);
  assert.match(html,/SYNTHETIC_ONLY/);
  assert.match(html,/disabled=""/);
});

test("employee workspace refresh uses personal endpoints without management telemetry or simulations", async () => {
  const paths = [];
  globalThis.fetch = async url => { paths.push(new URL(url).pathname); return json({}); };
  api.setStoredAuthToken("employee");
  const [, , telemetry, simulation] = await api.fetchWorkspaceState({user_id:"employee-1",role_view:"employee"});
  assert.deepEqual(paths.sort(), ["/api/v1/custody/overview", "/api/v1/state/overview"]);
  assert.equal(telemetry,null);
  assert.equal(simulation,null);
});


test("independent shadow review posts exact human final text under the current credential", async () => {
  let captured;
  api.setStoredAuthToken("manager-review-token");
  globalThis.fetch = async (url, init) => { captured = { url, init }; return json({ticket_id:"ticket-7",reviewer_id:"manager",score:{similarity_ratio:0.75,replaceability_score:42}}); };
  const finalText = "Actual checked deliverable\nwith a corrected second line.";
  const result = await api.submitShadowOutputReview({ticket_id:"ticket-7",human_final_text:finalText});
  assert.match(captured.url,/\/api\/v1\/scoring\/shadow-reviews$/);
  assert.equal(captured.init.headers.Authorization,"Bearer manager-review-token");
  assert.deepEqual(JSON.parse(captured.init.body),{ticket_id:"ticket-7",human_final_text:finalText});
  assert.equal(result.score.similarity_ratio,0.75);
  assert.equal(result.score.replaceability_score,42);
});

test("independent review entry excludes self-initiated work and non-management roles", () => {
  const outputs = [
    {ticket_id:"SELF-TICKET",initiator_id:"manager",ai_draft_text:"self draft",reviewed:false},
    {ticket_id:"OTHER-TICKET",initiator_id:"employee",ai_draft_text:"actual draft",reviewed:false},
    {ticket_id:"REVIEWED-TICKET",initiator_id:"employee",ai_draft_text:"prior draft",reviewed:true},
  ];
  const html = api.renderToStaticMarkup(api.createElement(api.ShadowOutputReviews,{outputs,reviewerId:"manager",roleView:"manager"}));
  assert.doesNotMatch(html,/SELF-TICKET/);
  assert.match(html,/OTHER-TICKET/);
  assert.match(html,/REVIEWED-TICKET/);
  assert.match(html,/已复核/);
  assert.match(html,/复核最终交付/);
  assert.doesNotMatch(html,/<textarea/,'final deliverable is never filled or submitted before explicit selection');
  for (const roleView of ["employee","leader","finance_tool"]) {
    assert.equal(api.renderToStaticMarkup(api.createElement(api.ShadowOutputReviews,{outputs,reviewerId:"employee",roleView})),"");
  }
});


test("pipeline preset compose preserves canonical inputs and unpublished candidate evidence", async () => {
  const calls = [];
  api.setStoredAuthToken("pipeline-manager");
  globalThis.fetch = async (url, init) => {
    calls.push({url,init});
    if (String(url).endsWith("/presets")) return json({presets:[{preset_id:"explicit-model",pipeline_title:"Model",source_skill_ball_ids:["ACTIVE-SOURCE"],default_test_payload:{amount:17},pipeline_instruction:"Preset template only",stages_preview:["one"]}]});
    return json({pipeline_id:"PIPE-CANDIDATE",proposal_id:"PROP-CANDIDATE",proposer_id:"creator",source_hash:"exact-code-hash",generated_code:"def run(payload): return payload",candidate_status:"CANDIDATE",validation_status:"UNVALIDATED",promoted:false,mounted_to_slot_id:null,master_ball_id:"BALL-CANDIDATE",master_ball:{status:"CANDIDATE"},source_skill_ball_ids:["ACTIVE-SOURCE"],evidence_provenance:{implementation:"PRESET_TEMPLATE",source_code_executed:false}});
  };
  const [preset] = await api.apiFetchPipelinePresets();
  assert.deepEqual(preset.stage_ball_ids,["ACTIVE-SOURCE"]);
  assert.deepEqual(preset.sample_input,{amount:17});
  const request = {preset_id:preset.preset_id,pipeline_title:preset.pipeline_title,source_skill_ball_ids:preset.stage_ball_ids,target_slot_id:"SLOT",test_payload:preset.sample_input};
  const result = await api.apiComposeSkillPipeline(request);
  assert.deepEqual(JSON.parse(calls[1].init.body),request);
  assert.equal(calls[1].init.headers.Authorization,"Bearer pipeline-manager");
  assert.equal(result.candidate_status,"CANDIDATE");
  assert.equal(result.validation_status,"UNVALIDATED");
  assert.equal(result.promoted,false);
  assert.equal(result.mounted_to_slot_id,null);
  assert.equal(result.generated_master_code,"def run(payload): return payload");
  assert.equal(result.source_hash,"exact-code-hash");
  assert.equal(result.evidence_provenance.source_code_executed,false);
  assert.equal(calls.length,2,"composing the candidate must not silently trigger execute");
});

test("pipeline preview is explicit sandbox-only execution and never upgrades business state", async () => {
  let captured;
  api.setStoredAuthToken("preview-manager");
  globalThis.fetch = async (url, init) => { captured={url,init}; return json({pipeline_id:"PIPE",execution_id:"PREVIEW",status:"SANDBOX_ONLY",ok:true,validation_status:"UNVALIDATED",execution_evidence:{business_execution_completed:false,process_passed:true},stage_breakdown:[{stage_index:1,stage_name:"Template arithmetic",source_ball_id:null,inputs:{value:2},outputs:{value:4}}],final_output:{value:4}}); };
  const request = {pipeline_id:"PIPE",ball_id:"CANDIDATE",payload:{value:2},sandbox_preview:true};
  const result = await api.apiExecuteSkillPipeline(request);
  assert.deepEqual(JSON.parse(captured.init.body),request);
  assert.equal(result.status,"SANDBOX_ONLY");
  assert.equal(result.executed_ok,true);
  assert.equal(result.execution_evidence.business_execution_completed,false);
  assert.equal(result.validation_status,"UNVALIDATED");
  assert.equal(result.stages[0].executed_ok,undefined,"lack of independent stage validation stays unknown");
  assert.deepEqual(result.stages[0].stage_output,{value:4});
  assert.equal(result.stages[0].ball_id,"");
  assert.deepEqual(result.final_output,{value:4});
});

test("unspecified pipeline model or implicit execute never sends a default business request", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return json({}); };
  api.setStoredAuthToken("manager");
  await assert.rejects(api.apiComposeSkillPipeline({preset_id:"",pipeline_title:"unknown generic",source_skill_ball_ids:[],target_slot_id:"S",test_payload:{}}),/请选择|明确选择/);
  await assert.rejects(api.apiExecuteSkillPipeline({pipeline_id:"PIPE",payload:{}}),/显式预览/);
  await assert.rejects(api.apiExecuteSkillPipeline({pipeline_id:"",payload:{},sandbox_preview:true}),/流水线 ID/);
  assert.equal(calls,0);
});

test("pipeline UI presents candidate creation separately from explicit sandbox preview", () => {
  const html = api.renderToStaticMarkup(api.createElement(api.AutonomousCommandStudioModal,{open:true,initialTab:"pipelines",onClose:()=>{},account:{user_id:"manager",role_view:"manager",slot_id:"S"},overview:{all_slots:[],all_balls:[]},custody:null,onClusterMutated:async()=>{},onToast:()=>{}}));
  assert.match(html,/创建候选模型（不挂载、不发布）/);
  assert.match(html,/来源引用不代表实际执行来源技能代码/);
  assert.match(html,/拟发布目标工位/);
  assert.doesNotMatch(html,/并实弹联立求解|Pipeline Ready|合成后挂载工位/);
});

test("candidate creator must defer publication to an independent authorized reviewer", () => {
  const html = api.renderToStaticMarkup(api.createElement(api.CandidateReview,{report:{proposal_id:"PIPE-PROP",proposer_id:"creator",promoted:false,source_hash:"hash",candidate_status:"CANDIDATE",validation_status:"UNVALIDATED"},reviewerId:"creator"}));
  assert.match(html,/另一名有权限的管理账号独立审核/);
  assert.doesNotMatch(html,/<form/);
});

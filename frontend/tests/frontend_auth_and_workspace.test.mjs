import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const bundleOut = path.join(frontendRoot, ".tmp_api_test_bundle.mjs");

async function loadBundledApi() {
  const esbuildBin = path.join(frontendRoot, "node_modules", ".bin", "esbuild");
  execFileSync(
    esbuildBin,
    [
      path.join(frontendRoot, "src", "api.ts"),
      "--bundle",
      "--format=esm",
      "--platform=neutral",
      `--outfile=${bundleOut}`,
    ],
    { cwd: frontendRoot, stdio: "pipe" }
  );
  return import(`${pathToFileURL(bundleOut).href}?t=${Date.now()}`);
}

test.after(() => {
  if (fs.existsSync(bundleOut)) {
    fs.unlinkSync(bundleOut);
  }
});

test("Bearer token injection, 401 eviction, snapshot delete & logout clearing", async () => {
  const api = await loadBundledApi();
  const originalFetch = globalThis.fetch;
  const capturedCalls = [];

  globalThis.fetch = async (url, init = {}) => {
    capturedCalls.push({ url: String(url), init });
    if (String(url).endsWith("/api/v1/auth/login")) {
      return new Response(
        JSON.stringify({
          token: "tok_m19_verify_123",
          account: { user_id: "u_boss", role_view: "boss" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (String(url).endsWith("/api/v1/auth/me")) return new Response(JSON.stringify({ account: { user_id: "u_boss", role_view: "boss" } }), { status: 200 });
    if (String(url).includes("/api/v1/snapshots/SNAP_401")) {
      return new Response(JSON.stringify({ detail: "expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ ok: true, deleted: true, snapshot_id: "SNAP_OK" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    api.setStoredAuthToken(null);
    assert.equal(api.getStoredAuthToken(), null);

    await api.loginAccount("u_boss", "123456");
    assert.equal(api.getStoredAuthToken(), "tok_m19_verify_123");

    await api.fetchOverview("boss", "u_boss");
    await api.saveClusterSnapshot({ label: "test_snap", note: "note" });
    await api.deleteClusterSnapshot("SNAP_OK");

    for (const call of capturedCalls.slice(1)) {
      const hdrs = call.init.headers;
      assert.equal(
        hdrs.Authorization,
        "Bearer tok_m19_verify_123",
        `Expected Bearer header on ${call.url}`
      );
    }

    await api.logoutAccount();
    assert.equal(api.getStoredAuthToken(), null);

    // Trigger 401 eviction check
    api.setStoredAuthToken("tok_stale_will_evict");
    await assert.rejects(() => api.deleteClusterSnapshot("SNAP_401"));
    assert.equal(api.getStoredAuthToken(), null);
  } finally {
    globalThis.fetch = originalFetch;
    api.setStoredAuthToken(null);
  }
});

test("deriveDepartmentTabs dynamically counts departments without fixed presets", async () => {
  const api = await loadBundledApi();
  const sampleAccounts = [
    { user_id: "1", department: "工程研发部" },
    { user_id: "2", department: "工程研发部" },
    { user_id: "3", department: "SMT制造中心" },
    { user_id: "4", department: "SMT制造中心" },
    { user_id: "5", department: "SMT制造中心" },
    { user_id: "6", department: "品质风控部" },
    { user_id: "7", department: "财税合规部" },
    { user_id: "8", department: "总办董事会" },
  ];
  const tabs = api.deriveDepartmentTabs(sampleAccounts);
  assert.deepEqual(tabs, [
    { key: "ALL", label: "全部 (8)" },
    { key: "工程研发部", label: "工程研发部 (2)" },
    { key: "SMT制造中心", label: "SMT制造中心 (3)" },
    { key: "品质风控部", label: "品质风控部 (1)" },
    { key: "财税合规部", label: "财税合规部 (1)" },
    { key: "总办董事会", label: "总办董事会 (1)" },
  ]);
  assert.equal(tabs.some((t) => t.label.includes("全部 (12)")), false);
});

test("frontend/src source code stays free of legacy furniture-era hardcodings", () => {
  const srcDir = path.join(frontendRoot, "src");
  const forbiddenPatterns = [
    /ROLE_PRESETS/,
    /全部 \(12\)/,
    /5 个部门/,
    /SLOT_FOLLOWUP_01/,
    /emp_chen/,
    /人体工学椅/,
    /美雅办公家具/,
    /BALL_REDLINE_FACTORY_FLOOR_PRICE/,
  ];

  function walk(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    const files = [];
    for (const ent of entries) {
      const full = path.join(dir, ent.name);
      if (ent.isDirectory()) {
        files.push(...walk(full));
      } else if (ent.name.endsWith(".ts") || ent.name.endsWith(".tsx")) {
        files.push(full);
      }
    }
    return files;
  }

  for (const filePath of walk(srcDir)) {
    const content = fs.readFileSync(filePath, "utf8");
    for (const pat of forbiddenPatterns) {
      assert.equal(
        pat.test(content),
        false,
        `Forbidden legacy pattern ${pat} found in ${path.relative(frontendRoot, filePath)}`
      );
    }
  }
});

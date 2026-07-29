const fs = require("fs");

const html = fs.readFileSync("index.html", "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) throw new Error("Inline application script not found");

const script = match[1];
new Function(script);

const instrumented = script.replace(
  /\s*start\(\);\s*\}\)\(\);\s*$/,
  "\n globalThis.__ethTest={localNaturalParse,normalizePlan,statesEqual,comparableState};\n})();"
);
new Function(instrumented)();

const cases = [
  [
    "刚转入两万",
    (p) => p.operations.some((o) => o.type === "add_transfer" && o.amount_eth === 20000),
  ],
  [
    "今天高点2300，已经砸了50个点",
    (p) =>
      p.operations.some((o) => o.type === "set_high" && o.price === 2300) &&
      p.operations.some((o) => o.type === "realize_points" && o.points === 50),
  ],
  [
    "昨天从最高2400跌到最低2320，今天最高2350，下午3点转入2万",
    (p) =>
      p.operations.some(
        (o) => o.type === "realize_points" && o.points === 80 && o.date_ref === "yesterday"
      ) &&
      p.operations.some((o) => o.type === "set_high" && o.price === 2350) &&
      p.operations.some(
        (o) => o.type === "add_transfer" && o.amount_eth === 20000 && o.time === "15:00"
      ),
  ],
];

for (const [input, check] of cases) {
  const plan = globalThis.__ethTest.normalizePlan(
    globalThis.__ethTest.localNaturalParse(input)
  );
  if (!check(plan)) {
    console.error(input, JSON.stringify(plan, null, 2));
    throw new Error("Parser regression");
  }
}

const verifiedDifference = globalThis.__ethTest.normalizePlan({
  operations: [{
    type: "realize_points",
    date_ref: "today",
    points: 60,
    source_high: 2300,
    source_low: 2250,
  }],
});
if (
  verifiedDifference.operations[0].points !== 50 ||
  !verifiedDifference.ambiguities.length
) {
  throw new Error("High/low difference verification regression");
}

const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
if (duplicates.length) throw new Error(`Duplicate ids: ${duplicates.join(", ")}`);
for (const requiredId of [
  "realizedFrom",
  "realizedTo",
  "syncConflictBar",
  "useCloudState",
  "overwriteCloudState",
]) {
  if (!ids.includes(requiredId)) throw new Error(`Missing UI control: ${requiredId}`);
}
if (!script.includes("source_high:sourceHigh||0") || !script.includes("source_low:sourceLow||0")) {
  throw new Error("Realized price range is not persisted in log detail");
}
if (!script.includes("statesEqual(state,current.data.state)") || !script.includes("showSyncConflict")) {
  throw new Error("Local/cloud preflight comparison is missing");
}
const syncA = {total: 10, logs: [{id: 1}], undo: {total: 5}, lastResult: "device A"};
const syncB = {logs: [{id: 1}], total: 10, undo: null, lastResult: "device B"};
if (!globalThis.__ethTest.statesEqual(syncA, syncB)) {
  throw new Error("Sync comparison should ignore transient fields and object key order");
}
if (globalThis.__ethTest.statesEqual(syncA, {...syncB, total: 11})) {
  throw new Error("Sync comparison missed a persisted state difference");
}

console.log(
  JSON.stringify(
    {
      scriptSyntax: "ok",
      parserCases: cases.length + 1,
      uniqueIds: ids.length,
      deepseekJsonMode: script.includes('response_format:{type:"json_object"}'),
      confirmationGate: script.includes("confirmOperations"),
      editablePreview: script.includes('data-field="price"'),
      editableRealizedRange: script.includes('data-field="source_high"') && script.includes('data-field="source_low"'),
      nonModalSyncConflict: html.includes('id="syncConflictBar"') && !html.includes('id="syncConflictBar"><dialog'),
      serverSync: script.includes("syncPush") && script.includes("syncPull"),
    },
    null,
    2
  )
);

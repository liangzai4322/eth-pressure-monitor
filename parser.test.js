const fs = require("fs");

const html = fs.readFileSync("index.html", "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) throw new Error("Inline application script not found");

const script = match[1];
new Function(script);

const instrumented = script.replace(
  /\s*start\(\);\s*\}\)\(\);\s*$/,
  "\n globalThis.__ethTest={localNaturalParse,normalizePlan,statesEqual,comparableState,mergeStates,uniqueLogs};\n})();"
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
  "syncNow",
]) {
  if (!ids.includes(requiredId)) throw new Error(`Missing UI control: ${requiredId}`);
}
if (!script.includes("source_high:sourceHigh||0") || !script.includes("source_low:sourceLow||0")) {
  throw new Error("Realized price range is not persisted in log detail");
}
if (!html.includes('src="assets/eth-monitor-logo.png"') || !html.includes('rel="icon"')) {
  throw new Error("Website logo integration is missing");
}
if (!script.includes("mergeStates(originalLocal,cloud,base)") || !script.includes("syncBaseKey()")) {
  throw new Error("Local/cloud three-way merge is missing");
}
const syncA = {total: 10, logs: [{id: 1}], undo: {total: 5}, lastResult: "device A"};
const syncB = {logs: [{id: 1}], total: 10, undo: null, lastResult: "device B"};
if (!globalThis.__ethTest.statesEqual(syncA, syncB)) {
  throw new Error("Sync comparison should ignore transient fields and object key order");
}
if (globalThis.__ethTest.statesEqual(syncA, {...syncB, total: 11})) {
  throw new Error("Sync comparison missed a persisted state difference");
}

const date = "2026-08-03";
const baseLog = {id:"base",time:`${date} 10:00`,action:"transfer",detail:{amount:10000,realized_points:0,consumed_eth:0},note:"",display:"转入 10,000 ETH"};
const localLog = {id:"local",time:`${date} 11:00`,action:"transfer",detail:{amount:5000,realized_points:0,consumed_eth:0},note:"",display:"转入 5,000 ETH"};
const cloudLog = {id:"cloud",time:`${date} 12:00`,action:"realized",detail:{amount:0,realized_points:3,consumed_eth:1000,realized_date_ref:"today"},note:"",display:"兑现 3 点"};
const transfer = (amount, recordedAt) => ({amount,time:"",recordedAt,note:""});
const baseState = {total:10000,baseline:10000,carryOver:10000,totalRealized:0,logs:[baseLog],daily:{[date]:{newTransfers:10000,realizedPoints:0,high:0,openingCarry:0,transfers:[transfer(10000,`${date} 10:00`)],touched:true}}};
const localState = {...baseState,total:15000,baseline:15000,logs:[baseLog,localLog],daily:{[date]:{...baseState.daily[date],newTransfers:15000,transfers:[...baseState.daily[date].transfers,transfer(5000,`${date} 11:00`)]}}};
const cloudState = {...baseState,total:9000,totalRealized:3,carryOver:9000,logs:[baseLog,cloudLog],daily:{[date]:{...baseState.daily[date],realizedPoints:3}}};
const merged = globalThis.__ethTest.mergeStates(localState, cloudState, baseState);
if (merged.total !== 14000 || merged.baseline !== 15000 || merged.totalRealized !== 3 || merged.logs.length !== 3) {
  throw new Error(`Bidirectional merge regression: ${JSON.stringify({total:merged.total,baseline:merged.baseline,totalRealized:merged.totalRealized,logs:merged.logs.length})}`);
}
if (merged.daily[date].newTransfers !== 15000 || merged.daily[date].realizedPoints !== 3) {
  throw new Error("Daily aggregate merge regression");
}
const legacyMerged = globalThis.__ethTest.mergeStates(localState,cloudState);
if (legacyMerged.total !== 14000 || legacyMerged.logs.length !== 3) {
  throw new Error("First merge without a stored sync baseline regression");
}
const duplicateCloudLog = {...localLog,id:"same-event-other-device"};
const duplicateCloudState = {...localState,logs:[baseLog,duplicateCloudLog]};
const deduped = globalThis.__ethTest.mergeStates(localState,duplicateCloudState,baseState);
if (deduped.total !== 15000 || deduped.logs.length !== 2) {
  throw new Error("Cross-device content fingerprint deduplication regression");
}
const otherDeviceLog = {...localLog,id:"different-transfer",time:`${date} 11:05`,note:"第二台设备的另一笔"};
const equalDeltaCloud = {...localState,logs:[baseLog,otherDeviceLog],daily:{[date]:{...localState.daily[date],transfers:[...baseState.daily[date].transfers,transfer(5000,`${date} 11:05`)]}}};
const combinedEqualDeltas = globalThis.__ethTest.mergeStates(localState,equalDeltaCloud,baseState);
if (combinedEqualDeltas.total !== 20000 || combinedEqualDeltas.daily[date].newTransfers !== 20000 || combinedEqualDeltas.logs.length !== 3) {
  throw new Error("Equal-sized but distinct concurrent additions were not combined");
}
const rolledLocal = {...baseState,lastActiveDate:"2026-08-04",high:0,carryOver:10000};
const oldCloud = {...baseState,lastActiveDate:"2026-08-03",high:2400};
const rolled = globalThis.__ethTest.mergeStates(rolledLocal,oldCloud,baseState);
if (rolled.lastActiveDate !== "2026-08-04" || rolled.high !== 0) {
  throw new Error("Natural-day rollover merge regression");
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
      automaticBidirectionalMerge: script.includes("mergeStates") && script.includes("unionLogs"),
      contentFingerprintDeduplication: true,
      serverSync: script.includes("syncPush") && script.includes("syncPull"),
    },
    null,
    2
  )
);

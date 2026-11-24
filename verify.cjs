const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {parseQuote, searchEvidence} = require("./finance.js");
const source = fs.readFileSync(path.join(__dirname, "evidence.js"), "utf8");
const data = JSON.parse(source.slice("const EVIDENCE = ".length).trim().slice(0, -1));

// Independently transcribed from Note 26-3, PDF p.104, amounts in KRW thousand.
const expected = {
  "2025-12-31":[1213903625, 2258010, 875900619, null],
  "2024-12-31":[708294579, 2157842, 744286650, null]
};
for (const [date, amounts] of Object.entries(expected)) {
  data.questions.forEach((q, i) => {
    const {row, amount} = searchEvidence(data, date, q);
    assert.equal(amount, amounts[i], date + " " + q.label);
    if (row) {
      assert.equal(row.page, 104);
      assert.equal(row.unit, "천원");
      assert.equal(row.date, date);
    }
  });
}
const encoded = [...data.rows, ...data.questions];
assert.ok(encoded.every(item => item.tokens <= data.sequenceLimit && item.vector.length === 384));
assert.equal(data.rows.reduce((sum, r) => sum + r.tokens, 0), data.indexTokens);
assert.ok(data.indexTokens <= data.indexBudget);
assert.equal(searchEvidence(data, "1900-01-01", data.questions[0]).amount, null);

assert.deepEqual(parseQuote("가상A 79/795사자", 3),
  {instrument:"가상A", direction:"매수", legs:[3790,3795], mean:3792});
assert.equal(parseQuote("가상B 82-", 4).mean, 4820);
assert.equal(parseQuote("가상B 82-", 4).direction, "매도");
assert.equal(parseQuote("가상A 79", 3).direction, "방향 미표시");
assert.equal(parseQuote("가상A 79/82사자", 3), null);
assert.equal(parseQuote("가상B 체결 문의", 3), null);
console.log("PASS: both periods, 8 disclosure answers, source page, model budgets, quote parsing.");

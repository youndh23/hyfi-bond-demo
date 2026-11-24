"use strict";
const $ = id => document.getElementById(id);
const number = value => value.toLocaleString("ko-KR");
const textNode = (tag, text) => Object.assign(document.createElement(tag), {textContent:text});

for (const [i, q] of EVIDENCE.questions.entries()) {
  $("item").add(new Option(q.label, String(i)));
}
const head = document.createElement("tr");
for (const label of ["부채 항목", ...EVIDENCE.columns]) head.append(textNode("th", label));
$("head").append(head);

function updateFiling() {
  const date = $("period").value;
  const question = EVIDENCE.questions[Number($("item").value)];
  const {ranking, row, amount} = searchEvidence(EVIDENCE, date, question);
  const rows = EVIDENCE.rows.filter(r => r.date === date);
  const page = rows[0].page;
  $("question").textContent = question.text;
  $("answer").textContent = amount === null ? "원문 확인 필요" : number(amount);
  if (amount !== null) $("answer").append(textNode("small", row.unit));
  $("formula").textContent = amount === null ? "만기표에 요청한 항목을 따로 구분한 행이 없습니다." :
    `3개월 이내 ${number(row.values[0])} + 이후 1년 이내 ${number(row.values[1])} (천원)`;
  $("source").href = EVIDENCE.source + "#page=" + page;
  $("table-note").textContent = `주석 26-3 · PDF ${page}쪽 · ${date} · 단위 천원`;
  $("pages").textContent = `${EVIDENCE.pages}쪽`;
  $("original").textContent = number(EVIDENCE.originalTokens) + " 토큰";
  $("index-size").textContent = number(EVIDENCE.indexTokens) + " 토큰";
  $("query-size").textContent = question.tokens + " 토큰";
  $("rows").replaceChildren(...rows.map(r => {
    const tr = document.createElement("tr");
    if (r === row) tr.className = "match";
    const title = textNode("th", r.label);
    title.scope = "row";
    tr.append(title, ...r.cells.map(v => textNode("td", v)));
    return tr;
  }));
  $("ranking").replaceChildren(...ranking.map(hit =>
    textNode("li", `${hit.row.label} · ${hit.score.toFixed(3)}${hit.row === row ? " · 항목 일치" : ""}`)));
}

function updateQuote() {
  const q = parseQuote($("quote").value, Number($("base").value));
  const rate = value => (value / 1000).toFixed(3) + "%";
  $("quote-result").textContent = q ? `${q.instrument} · ${q.direction} · ${rate(q.mean)}` : "원문 확인 필요";
  $("quote-detail").textContent = q ? "구성 금리 " + q.legs.map(rate).join(" / ") +
    (q.legs.length === 2 ? " · 대표 금리는 평균을 소수 셋째 자리까지 절사합니다." : "") :
    "가상 종목, 두세 자리 금리와 방향을 입력하세요. 세트는 0.5bp 간격만 지원합니다.";
}

for (const button of document.querySelectorAll("nav button")) {
  button.addEventListener("click", () => {
    for (const b of document.querySelectorAll("nav button")) {
      $(b.dataset.panel).hidden = b !== button;
      b.setAttribute("aria-pressed", String(b === button));
    }
  });
}
$("period").addEventListener("change", updateFiling);
$("item").addEventListener("change", updateFiling);
$("quote-form").addEventListener("submit", e => { e.preventDefault(); updateQuote(); });
$("base").addEventListener("change", updateQuote);
updateFiling();
updateQuote();

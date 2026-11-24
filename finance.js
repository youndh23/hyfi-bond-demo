"use strict";

function searchEvidence(data, date, question) {
  const ranking = data.rows.filter(row => row.date === date).map(row => {
    const score = row.vector.reduce((sum, v, i) => sum + v * question.vector[i], 0);
    return {row, score};
  }).sort((a, b) => b.score - a.score);
  const matches = ranking.filter(hit => hit.row.label === question.label);
  const row = matches.length === 1 ? matches[0].row : null;
  const amount = row && row.unit === "천원" ? row.values[0] + row.values[1] : null;
  return {ranking, row, amount};
}

function parseQuote(text, base) {
  const match = /^(가상[A-Z])\s+(\d{2,3})(?:\/(\d{2,3}))?\s*(사자|팔자|\+|-)?$/u.exec(text.trim());
  if (!match || ![2, 3, 4].includes(base)) return null;
  const [, instrument, first, second, side] = match;
  const mills = value => base * 1000 + Number(value.padEnd(3, "0"));
  const legs = [mills(first)];
  if (second) {
    const next = mills(second);
    if (Math.abs(next - legs[0]) !== 5) return null;
    legs.push(next);
  }
  const direction = {"+":"매수", "사자":"매수", "-":"매도", "팔자":"매도"}[side] || "방향 미표시";
  const mean = Math.floor(legs.reduce((sum, rate) => sum + rate, 0) / legs.length);
  return {instrument, direction, legs, mean};
}

if (typeof module !== "undefined") module.exports = {searchEvidence, parseQuote};

"""Página única da interface web (HTML/CSS/JS autocontido, sem bibliotecas externas)."""

PAGINA = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Analista SQL Delivery</title>
<style>
  :root {
    --bg: #f7f7f8; --surface: #ffffff; --ink: #1f2430; --ink-2: #5b6270; --line: #e6e8ec;
    --accent: #d64045; --accent-ink: #ffffff; --code-bg: #f1f2f4; --ok: #1a7f4b; --warn-bg: #fff4e5; --warn: #8a4b00;
    --err-bg: #fdecec; --err: #a12026;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #14161b; --surface: #1c1f26; --ink: #eceef2; --ink-2: #a2a8b5; --line: #2c3039;
      --accent: #ff6b70; --accent-ink: #14161b; --code-bg: #12141a; --ok: #5fd39a; --warn-bg: #33270f; --warn: #ffc277;
      --err-bg: #3a1a1c; --err: #ff9a9e;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
  header h1 { margin: 0 0 4px; font-size: 1.6rem; letter-spacing: -0.01em; }
  header p { margin: 0; color: var(--ink-2); }
  .badge { display: inline-block; margin-top: 10px; padding: 2px 10px; border: 1px solid var(--line); border-radius: 999px; font-size: .8rem; color: var(--ink-2); background: var(--surface); }
  form { display: flex; gap: 8px; margin: 24px 0 12px; }
  input[type=text] { flex: 1; min-width: 0; padding: 12px 14px; font: inherit; color: var(--ink); background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
  input[type=text]:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  button { padding: 12px 18px; font: inherit; font-weight: 600; color: var(--accent-ink); background: var(--accent); border: 0; border-radius: 10px; cursor: pointer; }
  button[disabled] { opacity: .6; cursor: progress; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .chip { padding: 6px 12px; font-size: .88rem; font-weight: 400; color: var(--ink-2); background: var(--surface); border: 1px solid var(--line); border-radius: 999px; }
  .chip:hover { color: var(--ink); border-color: var(--ink-2); }
  .card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .card h2 { margin: 0 0 8px; font-size: .78rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-2); }
  .msg { padding: 12px 14px; border-radius: 10px; }
  .msg.erro { background: var(--err-bg); color: var(--err); }
  .msg.recusa { background: var(--warn-bg); color: var(--warn); }
  pre { margin: 0; padding: 12px; overflow-x: auto; background: var(--code-bg); border-radius: 8px; font: .85rem/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; }
  .tabela { overflow: auto; max-height: 420px; border: 1px solid var(--line); border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: .92rem; }
  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { position: sticky; top: 0; background: var(--surface); color: var(--ink-2); font-weight: 600; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  img { max-width: 100%; height: auto; border-radius: 8px; background: #fff; }
  .meta { color: var(--ink-2); font-size: .85rem; margin-top: 8px; }
  .linha-topo { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .link { padding: 2px 8px; font-size: .8rem; font-weight: 500; color: var(--ink-2); background: transparent; border: 1px solid var(--line); }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Analista SQL Delivery</h1>
    <p>Pergunte em português. Veja o SQL, a tabela e o gráfico sobre dados sintéticos de delivery.</p>
    <span class="badge" id="provedor">carregando…</span>
  </header>

  <form id="form">
    <input type="text" id="pergunta" placeholder="Ex.: Qual o faturamento por categoria de restaurante?" maxlength="500" autocomplete="off" aria-label="Pergunta">
    <button type="submit" id="enviar">Perguntar</button>
  </form>
  <div class="chips" id="exemplos" aria-label="Exemplos de perguntas"></div>

  <div id="saida" aria-live="polite"></div>
</div>

<script>
const $ = (id) => document.getElementById(id);
const fmtNum = (v) => {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") return v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  return String(v);
};

function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
  }
  for (const f of filhos) n.append(f);
  return n;
}

function card(titulo, ...conteudo) {
  const c = el("section", { class: "card" });
  if (titulo) c.append(el("h2", { text: titulo }));
  c.append(...conteudo);
  return c;
}

function tabela(colunas, linhas) {
  const numericas = colunas.map((_, i) => linhas.length > 0 && linhas.every((l) => l[i] === null || typeof l[i] === "number"));
  const thead = el("thead", {}, el("tr", {}, ...colunas.map((c, i) => el("th", { class: numericas[i] ? "num" : "", text: c }))));
  const tbody = el("tbody", {}, ...linhas.map((l) => el("tr", {}, ...l.map((v, i) => el("td", { class: numericas[i] ? "num" : "", text: fmtNum(v) })))));
  return el("div", { class: "tabela" }, el("table", {}, thead, tbody));
}

function mostrar(d) {
  const saida = $("saida");
  saida.replaceChildren();
  if (d.recusa) {
    saida.append(card("Não respondi", el("div", { class: "msg recusa", text: d.recusa })));
    return;
  }
  if (d.erro) {
    saida.append(card("Erro", el("div", { class: "msg erro", text: d.erro })));
    if (d.sql) saida.append(card("SQL tentado", el("pre", { text: d.sql })));
    return;
  }
  if (d.explicacao) saida.append(card("Interpretação", el("div", { text: d.explicacao })));

  const botao = el("button", { type: "button", class: "link", text: "Copiar" });
  botao.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(d.sql); botao.textContent = "Copiado"; } catch { botao.textContent = "Selecione e copie"; }
    setTimeout(() => (botao.textContent = "Copiar"), 1500);
  });
  const sqlCard = card("", el("div", { class: "linha-topo" }, el("h2", { text: "SQL validado (somente leitura)" }), botao), el("pre", { text: d.sql }));
  saida.append(sqlCard);

  const infoLinhas = `${d.linhas.length} linha${d.linhas.length === 1 ? "" : "s"}` + (d.truncado ? " (resultado limitado)" : "");
  const tab = card("Resultado", tabela(d.colunas, d.linhas), el("div", { class: "meta", text: `${infoLinhas} · ${d.tempo_s.toFixed(2)}s · ${d.provedor}` }));
  saida.append(tab);

  if (d.grafico_png) {
    const img = el("img", { src: "data:image/png;base64," + d.grafico_png, alt: "Gráfico do resultado" });
    saida.append(card("Gráfico", img));
  }
  if (d.tentativas > 0) saida.append(el("div", { class: "meta", text: `A consulta foi corrigida automaticamente após ${d.tentativas} erro(s).` }));
}

async function perguntar(texto) {
  const botao = $("enviar");
  botao.disabled = true; botao.textContent = "Pensando…";
  try {
    const r = await fetch("/api/perguntar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pergunta: texto }) });
    mostrar(await r.json());
  } catch (e) {
    mostrar({ erro: "Não consegui falar com o servidor: " + e.message });
  } finally {
    botao.disabled = false; botao.textContent = "Perguntar";
  }
}

$("form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const t = $("pergunta").value.trim();
  if (t) perguntar(t);
});

(async () => {
  try {
    const info = await (await fetch("/api/info")).json();
    $("provedor").textContent = "Provedor: " + info.provedor;
    for (const ex of info.exemplos) {
      const b = el("button", { type: "button", class: "chip", text: ex });
      b.addEventListener("click", () => { $("pergunta").value = ex; perguntar(ex); });
      $("exemplos").append(b);
    }
  } catch { $("provedor").textContent = "servidor indisponível"; }
})();
</script>
</body>
</html>
"""

# Relatório de avaliação — acurácia por execução

- Provedor: `offline:regras`
- Data: 2026-11-16
- Banco: `delivery.db` (dados sintéticos)
- Casos: 62 (56 respondíveis + 6 que devem ser recusados)

## Resumo

| Métrica | Resultado |
|---|---|
| **Acurácia por execução** (casos respondíveis) | **60.7%** |
| SQL executável sem erro | 87.5% |
| Recusas corretas (escrita, dado inexistente, previsão) | 83.3% |
| Acertos que dependeram de autocorreção | 0 |
| Tempo médio por pergunta | 0.00s |

## Por nível de dificuldade

| Nível | Acertos | Total | Taxa |
|---|---:|---:|---:|
| Fácil | 11 | 13 | 84.6% |
| Médio | 22 | 25 | 88.0% |
| Difícil | 1 | 18 | 5.6% |
| Recusa (não deve responder) | 5 | 6 | 83.3% |

## Casos com erro

### f11 — Quantos pedidos entregues usaram o cupom BEMVINDO10?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT COUNT(*) AS total_pedidos
FROM pedidos p
WHERE p.status = 'entregue'
```

### f13 — Quantas avaliações com nota 5 foram registradas?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT ROUND(AVG(a.nota), 2) AS nota_media
FROM pedidos p
JOIN avaliacoes a ON a.id_pedido = p.id_pedido
```

### m11 — Qual o tempo médio de entrega por tipo de veículo do entregador?

- Situação: `resultado_errado` — número de linhas diferente (esperado 3, obtido 1)
- SQL gerado:

```sql
SELECT ROUND(AVG(p.tempo_entrega_min), 2) AS tempo_medio_entrega_min
FROM pedidos p
WHERE p.status = 'entregue'
```

### m23 — Quanto foi dado de desconto em cada cupom?

- Situação: `resultado_errado` — número de linhas diferente (esperado 3, obtido 1)
- SQL gerado:

```sql
SELECT ROUND(SUM(p.desconto), 2) AS total_descontos
FROM pedidos p
WHERE p.status = 'entregue'
```

### m24 — Qual o ticket médio dos pedidos que usaram cupom?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT ROUND(AVG(p.valor_total), 2) AS ticket_medio
FROM pedidos p
WHERE p.status = 'entregue'
```

### d01 — Quantos clientes fizeram mais de 5 pedidos entregues?

- Situação: `recusa_indevida` — Essa pergunta usa uma construção (limiar, comparação, acumulado...) que o baseline por regras não suporta.

### d02 — Qual restaurante tem a maior nota média, considerando só os que têm pelo menos 30 avaliações?

- Situação: `recusa_indevida` — Essa pergunta usa uma construção (limiar, comparação, acumulado...) que o baseline por regras não suporta.

### d03 — Qual a variação percentual do faturamento de cada mês em relação ao mês anterior?

- Situação: `recusa_indevida` — Essa pergunta usa uma construção (limiar, comparação, acumulado...) que o baseline por regras não suporta.

### d04 — Qual categoria de restaurante tem o maior ticket médio em cada cidade?

- Situação: `resultado_errado` — número de linhas diferente (esperado 10, obtido 1)
- SQL gerado:

```sql
SELECT r.categoria AS categoria, ROUND(AVG(p.valor_total), 2) AS ticket_medio
FROM pedidos p
JOIN restaurantes r ON r.id_restaurante = p.id_restaurante
WHERE p.status = 'entregue'
GROUP BY 1
ORDER BY ticket_medio DESC, categoria ASC
LIMIT 1
```

### d05 — Qual o faturamento acumulado ao longo dos meses?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT strftime('%Y-%m', p.data_pedido) AS mes, ROUND(SUM(p.valor_total), 2) AS faturamento
FROM pedidos p
WHERE p.status = 'entregue'
GROUP BY 1
ORDER BY 1
```

### d06 — Quantos restaurantes têm percentual de pedidos atrasados acima do percentual geral da plataforma?

- Situação: `recusa_indevida` — Essa pergunta usa uma construção (limiar, comparação, acumulado...) que o baseline por regras não suporta.

### d07 — Qual a participação percentual de cada forma de pagamento no faturamento?

- Situação: `recusa_indevida` — Essa pergunta usa uma construção (limiar, comparação, acumulado...) que o baseline por regras não suporta.

### d08 — Quantos clientes fizeram pedidos entregues tanto em janeiro quanto em dezembro?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT COUNT(DISTINCT p.id_cliente) AS clientes_ativos
FROM pedidos p
WHERE p.status = 'entregue' AND p.data_pedido >= '2025-01-01' AND p.data_pedido < '2025-02-01'
```

### d10 — Quais são os 3 restaurantes que mais faturam em cada categoria?

- Situação: `recusa_indevida` — Não consegui identificar qual métrica você quer calcular.

### d11 — Qual o faturamento dos restaurantes que cobram comissão de 23%?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT ROUND(SUM(p.valor_total), 2) AS faturamento
FROM pedidos p
WHERE p.status = 'entregue'
```

### d12 — Quantos entregadores fizeram mais de 80 entregas?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT COUNT(*) AS total_entregadores FROM entregadores
```

### d13 — Quantos pedidos entregues foram feitos por clientes que se cadastraram em 2025?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT COUNT(*) AS total_pedidos
FROM pedidos p
WHERE p.status = 'entregue'
```

### d14 — Qual a nota média dos pedidos entregues com atraso?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT ROUND(100.0 * SUM(CASE WHEN p.tempo_entrega_min > p.tempo_estimado_min THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_atrasados
FROM pedidos p
WHERE p.status = 'entregue'
```

### d15 — Quais restaurantes de Brasília faturaram mais de 20 mil reais?

- Situação: `resultado_errado` — número de linhas diferente (esperado 5, obtido 22)
- SQL gerado:

```sql
SELECT r.nome AS restaurante, ROUND(SUM(p.valor_total), 2) AS faturamento
FROM pedidos p
JOIN restaurantes r ON r.id_restaurante = p.id_restaurante
WHERE p.status = 'entregue' AND r.cidade = 'Brasília'
GROUP BY 1
ORDER BY faturamento DESC, restaurante ASC
```

### d16 — Que percentual dos pedidos entregues recebeu avaliação?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT ROUND(AVG(a.nota), 2) AS nota_media
FROM pedidos p
JOIN avaliacoes a ON a.id_pedido = p.id_pedido
```

### d17 — Qual a diferença de nota média entre pedidos entregues no prazo e pedidos entregues com atraso?

- Situação: `resultado_errado` — valores diferentes do esperado
- SQL gerado:

```sql
SELECT ROUND(100.0 * SUM(CASE WHEN p.tempo_entrega_min > p.tempo_estimado_min THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_atrasados
FROM pedidos p
WHERE p.status = 'entregue'
```

### d18 — Quais cidades tiveram faturamento acima da média das cidades?

- Situação: `recusa_indevida` — Essa pergunta usa uma construção (limiar, comparação, acumulado...) que o baseline por regras não suporta.

### r03 — Qual será o faturamento em 2026?

- Situação: `respondeu_indevidamente` — devolveu dados para uma pergunta que deveria ser recusada
- SQL gerado:

```sql
SELECT ROUND(SUM(p.valor_total), 2) AS faturamento
FROM pedidos p
WHERE p.status = 'entregue' AND p.data_pedido >= '2026-01-01' AND p.data_pedido < '2027-01-01'
```

## Como ler

A acurácia compara o **resultado da execução** da consulta gerada com o da consulta de referência (`evals/casos.json`), ignorando nomes e ordem das colunas e, em perguntas sem ranking, a ordem das linhas. Colunas ou linhas a mais contam como erro. Números têm tolerância de 0,011. Detalhes em `src/analista_sql/avaliacao.py`.

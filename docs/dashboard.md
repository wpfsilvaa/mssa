# Dashboard e políticas

## Abrir o laboratório

Com as dependências do projeto instaladas, execute na raiz do repositório:

```bash
PYTHONPATH=src .venv/bin/python -m mssa.dashboard
```

Abra **http://127.0.0.1:8765**. Após instalar o pacote, também é possível usar
`mssa-dashboard`. A porta pode ser alterada com `--port 8766`; `--scenarios caminho`
define a pasta de exemplos YAML. Não é necessário Node, instalar um frontend ou
acessar CDNs para usar a interface.

O servidor é local, escuta somente em loopback e usa o mesmo motor da CLI. Ele não
é uma implantação pública com autenticação. Cada aba cria sua própria sessão;
fechar ou pausar a interface interrompe as solicitações de avanço. Não há simulação
em segundo plano. O controle de velocidade muda a frequência de reprodução,
mantendo o `dt` do cenário.

## Explorar e editar

1. Abra `patrol_reaction.yaml` no seletor de exemplos. Ele contém um explorador em
   patrulha, um agente que reage a relatórios e uma patrulha adversária.
2. Use **Executar**, **Pausar**, **Passo** e **Reiniciar** para controlar a execução.
3. Selecione um agente pela lista ou pelo mapa. O painel direito mostra sua
   configuração e um resumo de velocidade, orientação e percepção atual.
4. Use **Posicionar no mapa** para definir a posição inicial. Na política de
   patrulha ou reação, **Adicionar pontos no mapa** acrescenta pontos à rota;
   pressione Esc para encerrar. A lista de coordenadas permite editar e remover pontos.
5. Configure sensores e enlaces no editor. Em **Cenário**, habilite opcionalmente
   uma missão de observação ou carregue uma configuração completa em YAML/JSON.
6. Clique em **Aplicar cenário**. Alterações são validadas antes de substituir a
   sessão, e aplicar reinicia o relógio e todos os estados.

O mapa em modo de edição mostra as posições iniciais do rascunho. Durante a
execução, mostra posições calculadas pelo motor. Os campos do editor continuam
representando a configuração inicial; o resumo acima do editor mostra valores
atuais. Uma edição pausa a reprodução e exige aplicar antes de continuar.

**Novo cenário** começa vazio. Adicione agentes, sensores e enlaces, ou importe
um arquivo. O navegador conserva o último rascunho válido para a próxima visita;
**Exportar YAML** salva um arquivo para uso no dashboard ou na CLI. Um rascunho
inválido não é reaberto automaticamente. **Exportar estado** salva o cenário e a
telemetria exibida, sem funcionar como checkpoint de continuação.

O editor remove referências em enlaces e missão quando um agente é excluído. Se
isso deixar a missão sem observadores ou sem alvos, a missão é desativada. Remover
o último sensor de um observador exige ajustar a missão antes de aplicar.

## Visualizações

- **Sensores:** setores com alcance, orientação relativa e campo de visão.
- **Comunicação:** círculos de alcance dos enlaces e conexões direcionais pela
  origem/destino indicados no tráfego. Pontos azuis mostram mensagens em trânsito.
- **Rotas:** pontos numerados e segmentos de patrulha.
- **Trajetórias:** últimas 600 posições exibidas por agente.
- **Tráfego:** últimos 200 eventos recebidos pela interface, distinguindo envio,
  entrega, perda aleatória, falta de alcance, fila cheia e expiração.
- **Percepção do selecionado:** esconde outros estados físicos no mapa e mostra
  apenas o agente, suas medições e relatórios recebidos. Cruzes amarelas são
  medições locais; azuis são medições recebidas. Círculos em torno das medições
  têm raio de duas vezes o desvio padrão, sem representar uma probabilidade
  conjunta calibrada de localização.

As animações são ilustrações dos eventos do motor: não modelam propagação física
de sinais. O marcador em trânsito interpola entre os extremos atuais do enlace,
com base no instante previsto de entrega. Um evento de descarte pode aparecer
sem mensagem em trânsito. Relatórios vazios também geram eventos.

A visão local é uma ferramenta visual para o analista. A aplicação recebe também
telemetria global; a restrição de informação das políticas é aplicada no motor,
por meio de `AgentContext`, independentemente da camada selecionada na interface.

## Políticas disponíveis

Sem `policy`, o agente mantém o modelo anterior de velocidade e orientação
constantes. Para patrulhar:

```yaml
policy:
  kind: patrol
  speed: 20
  arrival_radius: 1
  loop: true
  waypoints:
    - {x: 700, y: 200}
    - {x: 700, y: 500}
    - {x: 180, y: 200}
```

O agente orienta-se para o próximo ponto e reduz a velocidade do passo para não
ultrapassá-lo. Ao começar um passo dentro de `arrival_radius`, segue para o ponto
seguinte. Uma rota sem repetição termina com velocidade zero. O restante de um
passo que chega a um ponto não é reutilizado para percorrer o próximo segmento.
Portanto, variar `dt` pode alterar o tempo total da rota.

Para reagir:

```yaml
policy:
  kind: react
  speed: 25
  reaction: approach
  reaction_distance: 400
  max_observation_age: 5
  use_messages: true
  waypoints: []
```

| Campo | Comportamento |
| --- | --- |
| `reaction: approach` | Aproxima-se da posição medida, parando dentro do raio de chegada |
| `reaction: avoid` | Move-se no sentido oposto à posição medida |
| `reaction: hold` | Para enquanto houver contato válido |
| `reaction_distance` | Distância máxima até a medição para ativar a reação |
| `max_observation_age` | Idade máxima desde a medição, em segundos |
| `use_messages` | Inclui medições de relatórios entregues e ainda válidos |
| `waypoints` | Rota de patrulha usada quando não existe contato elegível |

Entre contatos elegíveis, a política prioriza a medição mais recente e depois a
mais próxima. Desempates são determinísticos por identificadores da medição/sensor.
Ela usa posições medidas, sem extrapolar movimento nem consultar a verdade atual
do alvo. Sem contato elegível nem rota, aguarda parada. Não existe memória adicional
de alvo na política: valem as últimas varreduras e relatórios do contexto.

Sensores não identificam afiliação ou identidade real do alvo. Portanto, a política
reage a **contatos anônimos**, inclusive contatos de aliados. Isso é igual para
plataformas aliadas e adversárias. Não há perseguição de um ID verdadeiro oculto.

Decisões usam varreduras do passo e mensagens entregues no início dele. Mensagens
recém-enviadas não ficam disponíveis no mesmo passo. Comandos e estado da política
só são consolidados se o passo inteiro for válido. A cinemática permite mudanças
instantâneas de orientação e velocidade; aceleração, raio de curva e colisões
ainda não são modelados.

## Monte Carlo e limites da primeira interface

A CLI executa os mesmos cenários e políticas:

```bash
python -m mssa scenarios/patrol_reaction.yaml --runs 100 --experiment-seed 42 --speed-std 1 --output patrol-batch.json
```

Para agentes com política, `speed_std` varia a velocidade comandada em `policy.speed`.
Para os demais, varia a velocidade inicial. O cenário efetivamente amostrado fica
registrado em cada resultado. O dashboard ainda executa uma sessão por vez e não
tem painel de análise de lotes Monte Carlo.

O servidor limita cada cenário da interface a 100 agentes, 200 sensores, 500 enlaces,
5000 pontos de rota e 1000 mensagens por fila. Há até 32 sessões em memória; sessões
inativas por uma hora são removidas ao criar uma nova. Esses limites pertencem ao
adaptador interativo, não alteram o esquema geral da CLI. Não há histórico completo,
reprodução de arquivos de eventos, banco de dados ou retomada de sessões após
reiniciar o servidor.

## Verificação

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
node --check src/mssa/dashboard/static/app.js
# Com o servidor rodando e Chrome instalado:
node tests/dashboard_smoke.mjs
```

O teste de navegador usa Chrome headless e Node com `WebSocket` nativo. Defina
`CHROME` para indicar outro executável Chromium e `MSSA_URL` para outra porta.
Ele verifica execução, edição, desenho de rota, entrega de mensagens,
importação/exportação, erros de validação, persistência e layout em tela pequena.

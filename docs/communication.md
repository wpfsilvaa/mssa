# Comunicação entre agentes

O módulo transmite relatórios de sensores por enlaces direcionais configurados
no cenário. Uma nova varredura gera um relatório por sensor para cada destinatário
configurado, incluindo varreduras vazias. O relatório contém somente medições locais
anônimas, sem a associação verdadeira dos alvos usada pelo avaliador da missão.

O exemplo [communication.yaml](../scenarios/communication.yaml) contém um observador,
um coordenador sem sensores, uma patrulha adversária e um aliado sem enlace.
Somente o coordenador recebe relatórios do observador. Estar no mesmo lado ou estar
perto de uma plataforma não basta para receber suas informações.

## Configuração

```yaml
communication_links:
  - sender_id: scout
    recipient_id: coordinator
    range: 200
    latency: 0.75
    loss_probability: 0.2
    queue_capacity: 4
    ttl: 3
```

| Campo | Semântica | Padrão |
| --- | --- | --- |
| `sender_id` | Agente que publica suas novas varreduras | Obrigatório |
| `recipient_id` | Agente que pode receber esses relatórios | Obrigatório |
| `range` | Distância máxima entre os agentes, em metros | Obrigatório, positiva |
| `latency` | Atraso nominal da entrega, em segundos | 0 |
| `loss_probability` | Probabilidade de descarte por tentativa elegível | 0 |
| `queue_capacity` | Máximo de mensagens em trânsito nesse enlace | 32 |
| `ttl` | Validade do relatório desde o envio, em segundos | 5 |

Um par origem/destino só pode aparecer uma vez. O enlace reverso é independente
e precisa ser declarado. As referências precisam existir e não podem apontar ao
mesmo agente. Afiliação não bloqueia nem cria enlaces: a configuração é explícita
e as regras são iguais para aliados, adversários e neutros.

Um agente sem sensores pode receber relatórios. Um enlace com remetente sem sensores
é válido, mas não gera tráfego nesta versão. Não há roteamento, retransmissão,
confirmação de recebimento, transmissão automática de mensagens recebidas ou filtros
por sensor. Cada enlace envia todas as novas varreduras locais do remetente.

## Ordem de processamento e limites

Para cada passo iniciado em `t`:

1. Remover relatórios recebidos cuja validade terminou.
2. Processar mensagens em trânsito, ordenadas pelo instante previsto de entrega.
   Expiração tem precedência sobre entrega. Uma mensagem devida só é entregue se
   origem e destino ainda estiverem em alcance no estado do mundo em `t`.
3. Para cada nova varredura local, tentar enviar um relatório em cada enlace de saída.
   Verificar alcance, capacidade de fila e perda aleatória, nessa ordem.
4. Agendar mensagens aceitas para `t + latency`, com validade até `t + ttl`.
5. Consolidar alterações da rede junto com o passo de simulação. Uma falha na
   propagação física não consome RNG, entrega mensagens nem altera contadores.

O alcance é inclusivo e verificado no envio e na entrega. Não se modela a trajetória
do sinal entre esses dois instantes. Uma mensagem fora de alcance é descartada,
sem esperar reconexão. Perdas aleatórias são sorteadas uma vez no envio, após
passar pelas verificações de alcance e fila. Mensagens perdidas não ocupam a fila.

Cada relatório ocupa uma vaga independentemente da quantidade de observações.
A fila representa mensagens em trânsito; não representa bytes, largura de banda
ou tempo de serialização de rádio. Se estiver cheia, a nova tentativa é descartada.
Entregas e expirações liberam vagas antes dos envios do mesmo passo. Varreduras
simultâneas são enviadas por ordem de ID do sensor, tornando a prioridade determinística.
Não há promessa de distribuição justa de capacidade entre sensores.

Entregas só ocorrem no início de um passo posterior ao envio, mesmo com latência
zero. Com `dt=0.25`, envio em 0 e latência 0.3, a entrega ocorre em 0.5. A métrica de
latência registra o atraso efetivo de 0.5, incluindo essa quantização.
Comparações temporais toleram pequenos resíduos de ponto flutuante.

O intervalo de execução continua sendo `[início, fim)`. Não há esvaziamento automático
das filas no final. Mensagens previstas para o instante final ou além permanecem
pendentes no resultado. Continuar a mesma `Simulation` preserva filas e fluxos RNG.

## Percepção do destinatário

`simulation.context(agent_id)` separa:

- `observations`: medições dos sensores do próprio agente;
- `messages`: relatórios efetivamente recebidos, com origem, destino, sensor,
  identificador de mensagem, instante de envio, instante de recebimento e validade.

As observações do relatório conservam `measured_at`. Seu `available_at` passa a ser
o instante real de entrega ao destinatário; a medição original do remetente não
é alterada. Posição e incerteza são transmitidas como medidas, sem consultar a
posição atual real do alvo na entrega. Não há fusão nem extrapolação.

O destinatário guarda somente o relatório mais recente por `(remetente, sensor)`.
Um relatório vazio substitui o anterior e informa ausência de detecções naquela
varredura. A validade é contada desde o envio e também limita a permanência na
percepção após a entrega. Em `t >= expires_at`, o relatório não fica disponível.
Limpar um relatório já recebido não incrementa o contador de mensagens expiradas
em trânsito. IDs de sensores repetidos em remetentes diferentes não se confundem.

Após `step`, o relógio já está no final do passo, enquanto as entregas foram
processadas no início. Um relatório com TTL menor que o passo pode já ter expirado
quando o contexto for consultado; os contadores ainda registram sua entrega.
Essa situação é evitada usando um passo adequado às escalas de latência e validade.

## Métricas de execução e Monte Carlo

O resultado de cada execução contém `network`. No lote Monte Carlo,
`summary.network` agrega os contadores de todas as execuções.

| Métrica | Significado |
| --- | --- |
| `attempted` | Tentativas de enviar relatórios por enlace, incluindo vazios |
| `enqueued` | Mensagens aceitas para trânsito |
| `delivered` | Entregas efetivas, mesmo se substituídas ou expiradas depois na percepção |
| `dropped_out_of_range` | Descartes por alcance no envio ou na entrega |
| `dropped_loss` | Descartes aleatórios no envio |
| `dropped_queue_full` | Novas tentativas rejeitadas por fila cheia |
| `expired` | Mensagens cuja validade acabou antes da entrega |
| `pending` | Mensagens ainda em trânsito no último início de passo processado |
| `delivery_rate` | Entregas divididas por tentativas, incluindo pendentes no denominador |
| `total_delivery_latency` | Soma dos atrasos efetivos de mensagens entregues |
| `mean_delivery_latency` | Soma dos atrasos dividida pela quantidade de entregas |

Vale a identidade:

```text
attempted = delivered + dropped_out_of_range + dropped_loss
            + dropped_queue_full + expired + pending
```

`enqueued` é uma contagem intermediária e não entra nessa soma. Uma mensagem aceita
pode ser entregue, expirar ou sair de alcance posteriormente. A taxa de entrega no
horizonte observado não estima sozinha a probabilidade de sucesso eventual das
mensagens pendentes. Uma fila pode conter uma mensagem com prazo no instante final,
pois esse instante ainda não foi processado.

No lote, taxas e médias são calculadas a partir das somas de contadores, ponderadas
pelo número de mensagens; não são médias simples das taxas de cada execução.
Sem tentativas, a taxa é `null`; sem entregas, a latência média é `null`.

Cada enlace tem RNG próprio, derivado da semente da execução e dos IDs dos extremos,
separado da dinâmica e dos sensores. Adicionar outro enlace não altera os sorteios
do enlace existente. Mundos, filas, caixas de entrada e RNG são novos a cada repetição.

```bash
python -m mssa scenarios/communication.yaml --output communication.json
python -m mssa scenarios/communication.yaml --runs 100 --experiment-seed 42 --output communication-batch.json
```

As métricas da missão `observe_targets` continuam avaliando detecções locais dos
observadores designados. Receber uma mensagem não conta como uma nova detecção
nessa missão. As políticas de reação já podem usar relatórios entregues para
alterar movimento, respeitando idade e distância das medições. Missões que exijam
informar um coordenador precisarão de um critério específico de sucesso.

O [dashboard](dashboard.md) permite editar enlaces, visualizar alcances, mensagens
em trânsito e eventos de envio/entrega/descarte. O motor expõe os eventos do último
passo em `Simulation.network_events` e mensagens em trânsito em `pending_messages`,
para uso do analista. Esses dados globais não entram no contexto das políticas.

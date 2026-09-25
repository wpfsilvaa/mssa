# Missões de observação

O cenário [observation.yaml](../scenarios/observation.yaml) demonstra dois
observadores aliados, uma patrulha adversária equipada com sensor e um sistema
adversário fixo. A missão exige detectar os dois adversários, com informação local
separada para cada agente. Não há compartilhamento automático entre aliados.

## Configurar sensores e missão

```yaml
schema_version: 1
simulation:
  duration: 20
  dt: 0.25
  seed: 42
environment:
  width: 1000
  height: 1000
mission:
  kind: observe_targets
  observer_ids: [observer]
  target_ids: [target]
agents:
  - id: observer
    x: 0
    y: 0
    heading: 0
    sensors:
      - id: forward
        range: 100
        field_of_view: 90
        heading_offset: 0
        period: 1
        probability_of_detection: 0.8
        position_std: 2
  - id: target
    affiliation: hostile
    x: 150
    y: 0
    speed: 5
    heading: 180
```

| Campo do sensor | Significado | Padrão |
| --- | --- | --- |
| `id` | Identificador único dentro da plataforma | Obrigatório |
| `range` | Alcance máximo em metros, maior que zero | Obrigatório |
| `field_of_view` | Abertura total em graus, entre 0 exclusivo e 360 inclusivo | 360 |
| `heading_offset` | Orientação relativa à plataforma, em graus | 0 |
| `period` | Intervalo nominal entre varreduras, em segundos | 1 |
| `probability_of_detection` | Probabilidade por alvo elegível em cada varredura | 1 |
| `position_std` | Desvio padrão do ruído normal independente em x e y, em metros | 0 |

Alcance e bordas do campo de visão são inclusivos. Um agente nunca detecta a si
mesmo. Plataformas coincidentes estão em alcance e não têm restrição de direção.
Todos os outros agentes podem ser detectados, independentemente da afiliação;
`target_ids` seleciona os alvos usados na pontuação da missão, não filtra o sensor.
Identificadores de sensores podem se repetir em plataformas diferentes.

O sensor não modela obstáculos, identificação de classe, falsos alarmes ou
dependência da probabilidade de detecção com a distância. O ruído altera somente
a medição, sem mover o alvo real. Uma posição medida pode ficar fora da área
do ambiente ou do alcance nominal por causa do ruído.

## Tempo e percepção

Cada sensor começa a varrer no primeiro passo da simulação. Uma varredura nominal
que cai entre passos é executada no primeiro início de passo elegível. Se `dt`
ultrapassar vários períodos, há apenas uma varredura naquele passo: períodos
perdidos são descartados, sem inventar observações de estados passados.
Escolha `dt <= period` para evitar essa perda de amostras.

Uma execução iniciada em zero observa o intervalo `[0, duration)`. Por exemplo,
com duração 2 s, `dt=0.5` e `period=0.5`, há varreduras em 0, 0.5, 1 e 1.5 s.
Um alvo que entra no alcance exatamente em 2 s ainda não foi observado nessa
execução. Continuar a mesma `Simulation` preserva relógio, agenda e fluxos aleatórios.

`simulation.context(agent_id)` retorna um `AgentContext` imutável com estado
próprio, tempo atual e observações locais. Cada observação contém posição medida,
sensor, identificador da medição, desvio padrão e instantes de medição/disponibilidade.
Para sensores próprios, a disponibilidade é imediata no tempo simulado. Após `step`, o contexto
mostra o estado físico atualizado e as medições feitas no início daquele passo.

O contexto conserva a última varredura de cada sensor até a próxima. Uma nova
varredura vazia limpa as medições daquele sensor. Os timestamps permitem reconhecer
medições antigas; não existe extrapolação, fusão, identidade persistente de contato
ou histórico de rastreamento. O identificador da medição só é único dentro da
plataforma. Ele não identifica o alvo.

O contexto também contém `messages`, com relatórios recebidos pelos enlaces
explicitamente configurados. Eles não entram nas observações locais nem contam
como novas detecções na missão `observe_targets`.

Os campos `target_id` e afiliação real dos contatos não aparecem nas observações.
A associação entre medição e alvo fica no avaliador de missão. O JSON é um artefato
para o analista e contém também a verdade do mundo; não deve ser usado como entrada
direta de uma futura política de agente.

Varreduras são calculadas antes do movimento e consolidadas junto com o passo.
Se a propagação falhar, percepções, métricas, progresso da missão e RNG dos sensores
não avançam. Sensores têm fluxos derivados da semente da execução e dos IDs da
plataforma e do sensor. Adicionar outro sensor não consome o fluxo de um existente.
Alvos são percorridos por ID; adicionar ou remover alvos pode alterar a sequência
de sorteios dentro de um sensor.

## Resultado da missão e do experimento

A missão usa observadores e alvos explicitamente declarados, sem restrição de lado.
Um adversário pode ser observador em outra configuração. Todos os observadores
declarados precisam de pelo menos um sensor, e observadores e alvos são conjuntos
distintos de agentes existentes.

O avaliador registra a primeira detecção de cada alvo por qualquer observador
designado. Detectar todos os alvos ao menos uma vez produz sucesso. Esse critério
é agregado pelo analista, sem presumir comunicação entre agentes. O sucesso fica
registrado mesmo que o contato seja perdido depois. A execução continua até a
duração configurada para manter o mesmo horizonte de comparação entre repetições.

| Campo | Interpretação |
| --- | --- |
| `mission.status` | `succeeded` ou `timeout` ao terminar; `in_progress` durante execução |
| `mission.first_detection_time` | Primeiro instante de detecção de algum alvo exigido |
| `mission.completion_time` | Primeiro instante em que todos os alvos já foram detectados |
| `mission.target_detections` | Primeira detecção de cada alvo observado, para avaliação |
| `total_scans` | Varreduras de todos os sensores, incluindo vazias |
| `total_detections` | Medições de todos os sensores, incluindo repetidas e contatos fora da missão |

Os tempos são instantes absolutos do relógio simulado; os cenários carregados
começam em zero. Campos de tempo não observados são `null`. Cenários sem missão
têm `mission: null`, mas ainda podem usar sensores e exportar percepções.

No resumo Monte Carlo, `mission_runs` é o denominador de `success_rate` e
`successful_missions` é o numerador. `runs_with_detection` é o denominador de
`mean_first_detection_time`. A média de conclusão usa somente execuções bem-sucedidas.
Por isso, comparar apenas a média de tempo entre configurações pode ocultar
execuções que nunca detectaram: analisar também a taxa de sucesso e as contagens.
Sem missões configuradas, contagens são zero e taxas/tempos são `null`.

O desvio de posição do experimento altera as condições físicas iniciais de todos
os agentes. Já `position_std` dentro de cada sensor altera suas medições a cada
varredura. Ambos são independentes e podem ser usados juntos. A probabilidade de
detecção pode gerar variação de sucesso mesmo sem incerteza nas condições iniciais.

```bash
python -m mssa scenarios/observation.yaml --output observation.json
python -m mssa scenarios/observation.yaml --runs 100 --experiment-seed 42 --position-std 5 --output batch.json
```

O módulo de comunicação já permite compartilhar essas observações por enlaces
com atraso, perdas, capacidade de fila e validade. Veja o [guia de comunicação](communication.md).

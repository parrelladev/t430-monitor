# Monitor do ThinkPad T430

Aplicativo desktop local em Python/Tkinter para observar o estado térmico e de recursos do ThinkPad T430. Esta primeira versão amplia o monitoramento existente sem prometer sensores que o sistema não exponha de forma confiável.

## Escopo do produto — primeira versão

O painel principal deve priorizar uma leitura rápida do estado atual e das tendências curtas:

| Métrica | Prioridade | Escopo inicial |
| --- | --- | --- |
| Temperaturas identificadas | Painel principal | Exibir sensores com nome fornecido por uma fonte do sistema; destacar CPU quando identificada e mostrar outras leituras reconhecidas. Preservar o histórico térmico recente já existente. |
| Uso da CPU | Painel principal | Mostrar utilização agregada em percentual, calculada a partir de leituras sucessivas do sistema. |
| Frequência da CPU | Painel principal | Mostrar frequência atual somente quando houver leitura válida; deixar claro quando for uma amostra instantânea. |
| Ventoinha | Painel principal | Mostrar rotação, estado e modo quando disponíveis pela interface do sistema. A leitura atual usa `/proc/acpi/ibm/fan`; não pressupor que todos os campos existam. |
| RAM | Painel principal | Mostrar memória usada e total, com unidades claras, usando informação fornecida pelo sistema operacional. |
| Bateria | Painel de detalhes | Mostrar carga e estado (carregando, descarregando ou conectada) quando expostos pelo sistema. Saúde/capacidade de projeto pode ser exibida nos detalhes apenas se houver fonte confiável. |
| Sensores térmicos adicionais | Painel de detalhes | Listar sensores identificados além da temperatura principal, sem inferir o componente pelo valor ou posição do sensor. |

### Métricas opcionais e dependências

A disponibilidade pode variar com BIOS, kernel, módulo `thinkpad_acpi`, drivers, firmware e hardware instalado. A GPU é opcional: leituras de temperatura, uso, frequência e memória da GPU dependem do adaptador presente e de um driver que exponha dados verificáveis. Não assumir que o T430 tenha uma GPU dedicada, nem que sensores de GPU estejam acessíveis. Essas métricas ficam no painel de detalhes quando uma fonte apropriada for detectada; caso contrário, permanecem indisponíveis.

Outras temperaturas, limites/estado de carga da bateria, rotação da ventoinha e frequência da CPU também dependem dos atributos realmente expostos. A primeira versão não deve inventar nomes de componentes nem estimar valores ausentes.

### Regra de confiabilidade

Quando não existir uma fonte legível e adequada para uma métrica, mostrar **“Indisponível”** (ou um estado equivalente claramente explicado). Distinguir ausência de sensor de uma leitura válida igual a zero; ignorar valores malformados ou fora de faixa plausível. Não substituir dados ausentes por estimativas silenciosas. O estado atual da máquina e as fontes disponíveis devem ser validados durante a implementação antes de anunciar disponibilidade específica.

## Fora do escopo inicial

- Overclock, ajuste de tensão ou alteração de limites de potência/frequência.
- Novos controles privilegiados ou escrita em interfaces de hardware. O monitoramento permanece sem privilégios. O controle manual de ventoinha já existente é separado e limitado ao helper atual; não ampliar seus poderes como parte desta etapa.
- Alertas avançados, perfis automáticos ou otimização de desempenho.

## Estrutura atual

`t430_monitor.py` contém a interface Tkinter e o controle de ventoinha já existente. `metrics.py` coleta temperaturas, campos da ventoinha, métricas de CPU, RAM e bateria sem depender da interface e retorna, por leitura, valor, unidade, estado (`available`, `unavailable` ou `invalid`), origem e identidade do sensor/rótulo quando expostas pela fonte. Leituras fora de faixa são inválidas e falhas não interrompem as demais métricas.

## Organização da interface

A janela compacta prioriza temperatura, uso e frequência da CPU, além da rotação e do estado da ventoinha. Um seletor permite traçar no histórico curto qualquer métrica numérica que esteja disponível; cada série usa unidade, escala e faixa apropriadas, e o gráfico informa quando está coletando amostras ou não há métrica disponível. RAM, bateria e temperaturas adicionais ficam numa seção recolhível. O ciclo de atualização permanece em 2 segundos, com um único callback Tk agendado por vez. O tamanho mínimo foi reduzido para manter os cartões e controles utilizáveis em janelas estreitas.

Temperaturas `hwmon` usam o nome do sensor e o rótulo do canal quando disponíveis; leituras `coretemp` são agrupadas sob CPU e mantêm a leitura mais quente. A lista `temperatures:` de `/proc/acpi/ibm/thermal` não identifica com confiabilidade o componente de cada posição. Portanto, seus valores são apresentados como canais indexados (`thermal[0]`, etc.) e nunca classificados automaticamente como CPU. Não são convertidos silenciosamente nem associados a componentes por posição.

O modo exibido da ventoinha é reavaliado em cada atualização a partir de `/proc/acpi/ibm/fan`, sem deduzi-lo de comandos emitidos na sessão. A leitura `level: auto` com status ACPI habilitado confirma modo automático; níveis de 1 a 7 com status habilitado e `disengaged` indicam modo manual. Ausência, combinação inconsistente ou resposta não reconhecida resulta em modo desconhecido. Ao fechar em modo manual, o app oferece solicitar retorno ao automático e mantém a janela aberta até a leitura ACPI confirmá-lo; se o modo estiver desconhecido, informa que não pode confirmar automático. A execução continua restrita ao helper atual e aos comandos `auto` e níveis de 1 a 7.

O controle usa `pkexec` para chamar somente o helper instalado. Se `pkexec` estiver ausente, a autenticação for cancelada/expirar ou o helper recusar/falhar, a interface apresenta uma mensagem correspondente e não trata o comando como aplicado. Um retorno bem-sucedido do helper é apenas uma solicitação aceita; o estado mostrado continua vindo da leitura ACPI. A política de autorização e os privilégios do helper não são modificados.

O uso total da CPU é calculado pela diferença entre duas amostras consecutivas da linha agregada `cpu` em `/proc/stat`; a primeira amostra, contadores ausentes/incompletos ou contadores inconsistentes produzem estado indisponível. A frequência atual usa primeiro `/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq` e, se não puder ser lida, tenta `cpuinfo_cur_freq`; os valores do sysfs em kHz são convertidos para MHz. Essas interfaces podem não estar expostas em todos os kernels, máquinas virtuais ou configurações de driver. Nenhuma leitura exige privilégios ou bibliotecas Python externas. Os valores são exibidos no painel atual, sem gráficos nesta etapa.

RAM usa `MemTotal` e `MemAvailable` de `/proc/meminfo`; “usada” é calculada como total menos disponível, e ambas são apresentadas em MiB. Se os campos estiverem ausentes, malformados ou incoerentes, as duas leituras aparecem como indisponíveis.

Baterias são detectadas por `type=Battery` em `/sys/class/power_supply`. A carga usa `capacity` quando disponível, ou a razão `charge_now/charge_full` (com alternativa `energy_now/energy_full`) quando esses pares são válidos. O estado vem do atributo `status`. Uma estimativa em minutos só é mostrada durante carga/descarga quando há `energy_now` ou `energy_full`, conforme o sentido, e `power_now` positivo na mesma fonte; é uma estimativa instantânea, não uma previsão garantida. Computadores sem bateria, interfaces sem esses atributos e dados malformados são apresentados como indisponíveis. Nenhum acesso exige privilégios ou pacotes externos.

## Validação

Execute os testes sem hardware específico com:

```sh
python3 -m unittest discover -s tests -v
```

Os testes usam dados simulados e não invocam o helper, `pkexec` nem escrevem em interfaces de ventoinha. Eles cobrem sensores e arquivos ausentes, conteúdo malformado, primeira amostra de CPU, isolamento de falhas entre métricas, ausência de bateria, erros de apresentação no ciclo Tk e falhas/recusa do helper.

Para validação manual em um ThinkPad T430, inicie `python3 t430_monitor.py` sem privilégios, confira temperatura/uso/frequência e abra a seção de detalhes para RAM, bateria e sensores. Compare as leituras somente com fontes locais legíveis: `/sys/class/hwmon`, `/proc/acpi/ibm/thermal`, `/proc/acpi/ibm/fan`, `/proc/stat`, `/sys/devices/system/cpu/cpu0/cpufreq`, `/proc/meminfo` e `/sys/class/power_supply`. A primeira leitura de uso da CPU deve aparecer indisponível enquanto reúne amostras; depois deve mostrar um percentual. Se uma fonte estiver ausente, a métrica correspondente pode aparecer como indisponível sem impedir as demais.

Sem acionar controles, verifique que o modo da ventoinha exibido acompanha `level` e `status` de `/proc/acpi/ibm/fan`; arquivos ausentes ou respostas incompletas devem resultar em modo desconhecido. O helper pode informar que `fan_control=N` ou não estar instalado: nesse caso, monitoramento continua disponível e o controle não pode ser aplicado. Não é necessário habilitar controle manual para validar sensores. Se já decidir testar um nível manual, a interface confirma antes do comando, usa somente o helper restrito e solicita autenticação; acompanhe a temperatura e retorne ao automático. A disponibilidade de temperaturas adicionais, frequência, rotação, carga/estado/tempo da bateria depende do kernel, firmware, drivers e atributos expostos. GPU e canais ACPI sem rótulo podem não existir ou não permitir identificação confiável.

## Requisitos

- Linux com Python 3 e Tkinter (`python3-tk` no Ubuntu/Debian).
- `sudo` e `install` para instalar o aplicativo no diretório do sistema.
- `pkexec`/PolicyKit é necessário somente para pedir mudanças manuais da ventoinha. O monitoramento não precisa de privilégios nem de bibliotecas Python externas.
- O módulo `thinkpad_acpi` e `/proc/acpi/ibm/fan` são necessários para as leituras ACPI da ventoinha. O controle manual requer ainda `fan_control=Y`.

Frequência da CPU depende de atributos `cpufreq`; temperaturas, ventilador, bateria e outras leituras variam com BIOS, kernel, drivers e hardware. GPU é opcional e pode não ter uma fonte legível. Sensores sem rótulo confiável são apresentados sem atribuição de componente; fonte ausente ou inválida resulta em “Indisponível”.

## Instalação

Na pasta do projeto:

```sh
./install.sh
```

O app e o coletor são copiados como arquivos de root para `/opt/t430-monitor`, independentemente do caminho original do projeto. O atalho é instalado em `$XDG_DATA_HOME/applications` (ou `~/.local/share/applications`). O helper restrito continua em `/usr/local/libexec/t430-fan-helper` e a política em `/usr/share/polkit-1/actions/org.codex.t430fan.policy`. O instalador verifica Python/Tkinter e informa falhas de autorização ou escrita. Ele não habilita `fan_control` nem altera a configuração do módulo.

## Executar

Após instalar, abra “Monitor T430” no menu de aplicativos ou execute:

```sh
/usr/bin/python3 /opt/t430-monitor/t430_monitor.py
```

Para executar a cópia de desenvolvimento sem instalar:

```sh
python3 t430_monitor.py
```

## Desinstalação

Na pasta do projeto:

```sh
./uninstall.sh
```

O desinstalador remove apenas os dois módulos instalados em `/opt/t430-monitor`, o helper e a ação PolicyKit com nomes exatos deste app, e o atalho `t430-monitor.desktop` do diretório de aplicações do usuário atual. Não remove configurações pessoais, a configuração `thinkpad_acpi`, outros arquivos no diretório do app, nem diretórios que ainda contenham arquivos. Se `XDG_DATA_HOME` usado na instalação era personalizado, use o mesmo valor ao desinstalar.

## Diagnóstico

- Se o atalho não aparecer, confirme que `t430-monitor.desktop` está em `$XDG_DATA_HOME/applications` e que `/opt/t430-monitor/t430_monitor.py` existe.
- Se a instalação indicar Tkinter ausente, instale `python3-tk` e repita `./install.sh`.
- Se rotação, modo ou estado da ventoinha estiverem indisponíveis, confira se `/proc/acpi/ibm/fan` existe e se `thinkpad_acpi` está carregado.
- Se o controle manual disser que está desabilitado, consulte `/sys/module/thinkpad_acpi/parameters/fan_control`. O valor `N` impede o helper de aplicar níveis; o monitoramento continua funcionando. O controle requer configuração explícita do módulo e reinicialização, conforme a configuração administrada pelo usuário.
- Se a autenticação não abrir, confirme que `pkexec` está instalado e que o serviço PolicyKit está disponível. Cancelamento ou falha do helper não é tratado como alteração aplicada.
- CPU, temperatura, bateria e GPU podem aparecer como indisponíveis quando o kernel, driver ou hardware não expõe os atributos correspondentes. A primeira amostra de uso da CPU é indisponível por desenho; aguarde o próximo ciclo de 2 segundos.

Para a validação manual dos sensores no T430 e os testes simulados, consulte a seção [Validação](#validação).

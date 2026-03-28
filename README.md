# francais-anki

Automacao em Python para gerar decks `.apkg` do Anki com foco em pronuncia e compreensao oral em frances. O pipeline usa `edge-tts` para sintetizar audio, `pydub` + `ffmpeg` para concatenar as duas locucoes com pausa, `genanki` para empacotar o deck e `AnkiConnect` como etapa opcional de importacao/atualizacao no Anki Desktop.

## 1. Arquitetura

### Modulos principais

- `src/francais_anki/cli.py`: ponto de entrada da aplicacao.
- `src/francais_anki/models.py`: modelos de dados do JSON de entrada.
- `src/francais_anki/audio.py`: selecao de vozes, sintese TTS e concatenacao final do audio.
- `src/francais_anki/voice_discovery.py`: descoberta dinamica de vozes via edge-tts e classificacao por regioes.
- `src/francais_anki/anki_model.py`: note type, templates e CSS do Anki.
- `src/francais_anki/builder.py`: cria o deck/subdeck, gera as notas e escreve o `.apkg`.
- `src/francais_anki/anki_connect.py`: cria modelo/deck no Anki, envia midia e cria/atualiza notas quando o AnkiConnect estiver disponivel.
- `src/francais_anki/utils.py`: logging, hashes estaveis, leitura de JSON e sanitizacao.

### Fluxo ponta a ponta

1. O CLI descobre dinamicamente as vozes francesas disponiveis via `edge-tts`.
2. O CLI le o JSON e valida a estrutura basica.
3. Cada frase recebe um GUID estavel a partir do texto em frances.
4. O pipeline escolhe duas vozes francesas de forma deterministica por frase, considerando pesos por regiao (FR-FR, FR-BE/CH, FR-CA).
5. O `edge-tts` gera duas locucoes: uma normal e outra um pouco mais lenta.
6. O `pydub` concatena `Audio1 + 2s de pausa + Audio2` em um unico `.mp3`.
7. O `genanki` cria 1 nota por frase e 2 cartas por nota, com midia embutida no `.apkg`.
8. Depois da geracao do `.apkg`, a aplicacao tenta sincronizar com o Anki via AnkiConnect.
9. Se o AnkiConnect nao estiver disponivel, a execucao termina com sucesso e apenas registra um aviso.

### Estrategia de atualizacao

- No `.apkg`, cada nota usa `guid` estavel baseado em hash da frase em frances.
- No AnkiConnect, como nao existe um campo extra de identificador no modelo fixo, a atualizacao procura notas existentes por `deck + note type + FraseFR`.
- Se encontrar notas, atualiza os campos e reforca as tags.
- Se nao encontrar, cria uma nova nota.

## 2. Dependencias

### Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ou:

```bash
pip install -e .
```

### Bibliotecas usadas

- `edge-tts`
- `genanki`
- `pydub`
- `requests`

### Dependencia de sistema

`pydub` depende de `ffmpeg` no `PATH`.

No macOS:

```bash
brew install ffmpeg
```

## 3. Codigo

### Estrutura de pastas

```text
francais-anki/
  data/
    input.example.json
    input.minimal.json
  output/
    apkg/
    logs/
    media/
  src/
    francais_anki/
      __main__.py
      anki_connect.py
      anki_model.py
      audio.py
      builder.py
      cli.py
      config.py
      models.py
      utils.py
```

### Comportamentos implementados

- leitura de JSON
- 1 nota por frase
- 2 cartas por nota
- note type `FR - Frase / Audio / IPA`
- deck principal + subdeck por tema
- tags `alliance-francaise`, nivel e tema
- nome de arquivo de audio sanitizado com hash previsivel
- audio final em um unico arquivo `[sound:arquivo.mp3]`
- prioridade para gerar `.apkg`
- tentativa opcional de importacao/atualizacao via AnkiConnect
- logs claros em `output/logs/run.log`

## 4. Exemplo de JSON

### Minimo

Arquivo: `data/input.minimal.json`

### Um pouco maior

Arquivo: `data/input.example.json`

Os dois exemplos ja estao no repositorio e podem ser usados diretamente.

## 5. Como executar

Com o ambiente ativado:

```bash
PYTHONPATH=src python3 -m francais_anki.cli --input data/input.example.json
```

Ou, se instalado com `pip install -e .`:

```bash
francais-anki --input data/input.example.json
```

Para processar todos os JSONs de um diretorio de forma recursiva:

```bash
PYTHONPATH=src python3 -m francais_anki.cli --input-dir data/todo
```

O diretorio e parametrizavel, entao voce pode apontar para qualquer pasta com arquivos `.json`.

Para gerar apenas o `.apkg` sem tentar AnkiConnect:

```bash
PYTHONPATH=src python3 -m francais_anki.cli --input data/input.example.json --skip-ankiconnect
```

Para endurecer a geracao de audio em lotes maiores:

```bash
PYTHONPATH=src python3 -m francais_anki.cli \
  --input data/input.example.json \
  --tts-connect-timeout 20 \
  --tts-receive-timeout 90 \
  --tts-retries 3 \
  --tts-final-retry-pass
```

Saidas:

- audios em `output/media/`
- pacote em `output/apkg/`
- log em `output/logs/run.log`
- reuso automatico de audio ja existente em `output/media/`
- notas com falha permanente de audio ficam fora do `.apkg`, mas o lote continua e registra o resumo no log

## 6. Observacoes finais

### Limitacoes honestas

- A atualizacao via AnkiConnect depende de a frase francesa permanecer igual, porque o modelo nao tem um campo extra de identificador.
- O script nao foi executado de ponta a ponta neste repositorio vazio porque as dependencias Python e o `ffmpeg` ainda nao foram instalados aqui.
- A sintese TTS depende de acesso de rede no momento da execucao local.

### Melhorias futuras

- paralelizar geracao de audio para lotes maiores
- adicionar testes automatizados com mocks para `edge-tts` e AnkiConnect
- exportar um relatorio JSON da execucao
- permitir sobrescrever vozes por nota

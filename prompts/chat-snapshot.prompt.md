Sua tarefa é consolidar todo o conhecimento útil desta conversa em um ÚNICO prompt estruturado para reinicializar o contexto em um novo chat.

Objetivo: preservar decisões, correções e padrões — eliminando redundâncias, erros antigos e discussões irrelevantes.

Siga rigorosamente as instruções:

1. Extraia apenas o que é útil e reutilizável:
   - Regras e padrões definidos
   - Correções feitas ao longo da conversa
   - Preferências explícitas do usuário
   - Estruturas de saída (formatos, JSONs, templates)
   - Decisões finais (ignore ideias descartadas)

2. Remova completamente:
   - Tentativas erradas ou corrigidas
   - Explicações desnecessárias
   - Conversas intermediárias
   - Qualquer ambiguidade

3. Resolva conflitos:
   - Se houver múltiplas versões de algo, mantenha apenas a versão FINAL válida

4. Organize o resultado nas seções:

## CONTEXTO DO PROJETO
(descreva o objetivo do chat em poucas linhas)

## REGRAS E DIRETRIZES
(lista clara e objetiva)

## PADRÕES E FORMATOS DE SAÍDA
(ex: JSON, templates, estrutura de resposta)

## CORREÇÕES IMPORTANTES
(apenas o que mudou comportamento do modelo)

## PREFERÊNCIAS DO USUÁRIO
(estilo, nível, restrições, etc.)

## EXEMPLOS FINAIS (SE NECESSÁRIO)
(apenas exemplos corretos e validados)

5. Transforme tudo isso em um PROMPT INICIAL pronto para ser usado em um novo chat:
   - Escreva em tom de instrução direta ao modelo
   - Sem explicar o que você está fazendo
   - Sem mencionar a conversa anterior

6. O resultado final deve ser:
   - Claro
   - Enxuto
   - Sem redundância
   - Otimizado para performance

Se algo não for 100% claro ou estiver inconsistente, OMITA.

Saída final: apenas o prompt pronto.
# Segurança

Este código foi preparado como uma árvore nova, com lista explícita de arquivos. Nenhum histórico Git anterior, credencial, sessão, conversa, fila, log, backup ou configuração de execução faz parte da distribuição.

## Limites de confiança

- Aplicativo de usuário único em loopback. Não exponha a porta na rede, em túneis ou por proxy reverso.
- Host/Origin, token local por processo, JSON obrigatório e cabeçalhos de proteção reduzem CSRF, DNS rebinding e leitura por sites externos.
- O token da interface é um segredo temporário de execução, não uma credencial incluída no código. Processos com acesso ao mesmo usuário do sistema não são isolados por esse mecanismo.
- Configuração, executáveis e arquivos locais precisam ser confiáveis. Respostas de modelos e transcripts não ampliam autorização.
- Travas e limites de arquivos são mecanismos de coordenação; não substituem uma sandbox do sistema. Uma troca concorrente de links por um processo malicioso com acesso local está fora desta fronteira de confiança.
- Dados de execução devem ficar em um diretório privado, fora de qualquer repositório. Não envie relatórios ou conhecimento a um provedor sem revisar o conteúdo e autorizar esse envio.
- A verificação automática de padrões de segredos é incompleta. Não equivale a uma garantia de ausência de informação confidencial.

## Verificações de publicação

1. Revisão humana dos arquivos e das diferenças em relação à instalação privada.
2. Testes com dados sintéticos e diretórios temporários, sem contas reais.
3. Varredura Gitleaks da árvore selecionada e do novo histórico Git, com saída redigida.
4. Conferência dos nomes de arquivos e metadados do commit; autor usa endereço GitHub noreply.
5. ZIP criado somente com arquivos rastreados pelo Git.

A CI tem permissões apenas de leitura e verifica testes e segredos. Não usa chaves dos provedores. Dependências de actions são fixadas por commit.

## Relatar um problema

Use a opção privada “Report a vulnerability” na aba Security, se estiver habilitada. Não publique tokens, conversas, caminhos pessoais ou detalhes exploráveis em uma issue pública. Caso encontre uma credencial real publicada, o titular deve revogá-la: apagar o arquivo não elimina cópias já obtidas.

# Viveiro · demonstração

Versão de demonstração do sistema de gestão de viveiro de mudas de café, com uma cópia dos dados do viveiro
(sem fotos e sem nomes de usuário). Roda inteira no navegador: o que for registrado fica salvo só no navegador de quem usa ("Restaurar dados" volta ao exemplo).

Este repositório guarda apenas o site já montado; ele é gerado automaticamente a partir do projeto principal.

O radar de chuva, as nuvens do satélite e o aviso de chuva vêm da REDEMET (DECEA). A tarefa em
.github/workflows/tempo.yml busca os dados a cada ~15 minutos, com a chave guardada como segredo do repositório,
e publica o site com eles.

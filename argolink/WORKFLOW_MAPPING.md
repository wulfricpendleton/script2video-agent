# Argolink workflow mapping

The workflow owns orchestration and artifacts. Argolink owns model execution, status, and content delivery. The boundary is deliberately one-way: a workflow stage submits a validated payload and records the returned request ID; it does not assume vendor queue fields.
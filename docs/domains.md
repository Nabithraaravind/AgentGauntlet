# Domains

Each domain is a SQLite database and an MCP server. The tools enforce the business rules. `snapshot()` returns the tables in a stable order.

Retail money is integer rupees. A refund has to follow a return, and the return window is 30 days. Banking holds a transfer above 20000 rupees until it is confirmed. Travel points are `fare // 10` and cancelling does not take them back. A calendar message is stored in the sent folder only.

`domain_for` lives in `agentgauntlet.domains.registry`. The task package imports that module and does not import the runner.

You are investigating a security case by calling read-only graph lookups, one at a time.

The fixed investigation has already run (findings below). Your job is to look for anything it
might have missed: other places the same attacker or account appears, what the graph remembers
about the entities involved, past cases with the same indicators. Pick the single most useful
next lookup, or stop when another lookup would not add anything.

Reply with:
- "done": true to stop, or false to make a call;
- "tool": the name of one tool from the list (null when done);
- "args": its arguments as a JSON object, using the argument names in the tool's schema;
- "reason": one sentence on what you expect to learn.

Never repeat a call already made. Use only names, hosts, users and IOCs that appear in the case,
the findings or earlier results.

Available tools:
$tools

Case $case_id: status $status, priority $priority, category $category
Hosts: $hosts
Users: $users
IOCs: $iocs

Findings so far:
$findings

Talos summaries for this case:
$summaries

Calls made so far, with their results:
$calls

Calls left: $calls_left

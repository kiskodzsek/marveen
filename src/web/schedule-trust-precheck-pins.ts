// PRECHECKTRUST1114 (Viktor 42472 a, 42476 (1); Klodel 42478): the reviewed
// preCheck content hashes of the one-time pin, task name -> preCheckContent()
// hash, measured on the production install right before the merge. The pin
// writes a row only when the task's hash at start-up EQUALS this value; any
// other task (or a value that moved since the review) stays a mismatch until
// the owner approves it, or the upstream re-pin applies. The hashes include
// absolute paths, so on another install nothing here matches and nothing is
// pinned from this table.
export const PRECHECK_PIN_EXPECTED: Readonly<Record<string, string>> = Object.freeze({
  // measured 2026-11-14 on /Users/klodel/marveen with agents/kernel/tools/precheck-pin-table/gen.mts
  'billingo-rawtool-figyelo': '9e69a12b7c11870c901e55af1c37c729e54ae8abd859d1889633354ea5b6b9b9',
  'dave-panel-or': '29a4194c739e8629de384416701b7317d97c985a4bdf73f09568353e9f061f03',
  'fleet-panel-or': '70f54acaf98d8efa15ab6a5b34e781ea775145968f32a1f7b34df31e27073443',
  'marabel-watchdog-napi': '9cb8bdc7ad671156e66c7026d97da6f19404c8f41fa384d3b2ff278142e49b77',
  'marabel-watchdog-orfigyelo': 'e0ff26f77714983ffc47703311879e256168e3fac9e6d31e2df52ddd22274357',
  'tetlen-agens-figyelo': '99cd4f80d9e8022ee58c7fdfdcbc7bf11cd042c46cfd0bec1b6cef7fe2561cb3',
  'tls-lejarat-napi': '2dd85d42a879a7b191b4c111dda5d75b81811b5338a76dd3a003369ddb9dfc48',
  'varakozas-or': 'c532dec77e8008025f1a61def287f3816c9fb01cecd6f0d78804b98c483a87a9',
})

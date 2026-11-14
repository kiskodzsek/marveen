import { isAbsolute, join } from 'node:path'
import { PROJECT_ROOT } from '../config.js'
import { SCHEDULED_TASKS_DIR } from './scheduled-tasks-io.js'

// Where a task's preCheck script lives. Relative -> beside the task's SKILL.md;
// absolute -> as given; a leading {{PROJECT_ROOT}} / {{INSTALL_DIR}} -> the
// install root. The placeholder form exists for SHIPPED tasks that gate on a
// repo script: the node seeder copies task-config.json without template
// rendering, and update.sh's seed refresh never adds a new file to an existing
// task dir, so neither a hard-coded path nor a script beside the SKILL.md would
// reach every install. (PRECHECKTRUST1114: moved out of schedule-runner.ts, which re-exports it;
// the runner runs this path and schedule-trust.ts hashes it, so both import it from here.)
export function resolvePreCheckPath(taskName: string, preCheck: string): string {
  const rooted = preCheck.replace(/^\{\{(PROJECT_ROOT|INSTALL_DIR)\}\}(?=\/)/, PROJECT_ROOT)
  return isAbsolute(rooted) ? rooted : join(SCHEDULED_TASKS_DIR, taskName, rooted)
}

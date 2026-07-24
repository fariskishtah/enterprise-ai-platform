# Live factory demo

The simulator is controlled by `demo_tools_enabled`. It is disabled by default, and
backend configuration rejects enabling it in production. Authentication, company
scope, and roles are enforced by the API, not only by the UI.

## Control flow

Administrators and engineers use `/demo/control` to select an authorized factory,
machine, scenario, and speed. Every update requires an explicit **Advance** action;
there is no infinite worker. Pause, resume, stop, duplicate-start protection, and
terminal states are persisted. The UI polls current state every three seconds only
while a run is active.

Exactly eight fixed-seed scenarios are available:

1. Normal operation
2. Gradual degradation
3. Warning threshold
4. Critical condition
5. Sensor fault
6. Data dropout
7. Maintenance intervention
8. Recovery to normal

Each step produces bounded simulation readings, a machine-risk assessment, and a
timeline event. Warning or critical states produce one alert and one operational
action for that run.

## Factory map and TV mode

`/factories/{factoryId}/map` shows existing machines on a two-dimensional layout.
Coordinates range from 0–100, reference only machines in that factory, and do not
infer physical location. Administrators and engineers can persist a layout;
operators can view it. A normal list remains available for keyboard users.

`/factories/{factoryId}/tv` is authenticated, read-only, responsive, and refreshes
every five seconds. It shows factory state, machine count, active alerts, urgent
actions, connection state, and the last update. It exposes no edit controls or
engineer diagnostics.

## Reset and production safeguards

Reset requires administrator confirmation. A run records the exact IDs it generated;
reset deletes only those readings, assessments, alerts, actions, and timeline
events, then removes the run. Customer records and other demo runs are untouched.
There is no general database-reset endpoint.

The guided tour is lightweight and optional. Completion can be stored in browser
local storage and never changes server data. No industrial protocol, CAD import,
3D rendering, or public anonymous dashboard is included.

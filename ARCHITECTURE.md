# Frontend architecture

The frontend is organized by feature while preserving the existing API contracts and visual class names.

- `src/App.jsx`: page orchestration, state and refresh flows.
- `src/api/`: HTTP client and endpoint modules.
- `src/config/dashboard.js`: dashboard constants and visual metadata.
- `src/shared/dashboardUtils.js`: formatting and pure presentation helpers.
- `src/hooks/`: reusable React hooks.
- `src/components/layout/`: shared header and language components.
- `src/features/strategies/`: strategy cards and strategy-specific presentation.
- `src/features/adaptive-research/`: local adaptive research presentation.
- `src/features/opportunities/`: opportunity scanner presentation.
- `src/features/experiments/`: experiment setup, stop and retry dialogs.
- `src/styles/foundation.css`: design tokens and global styles.
- `src/styles/dashboard.css`: dashboard component and responsive styles.

The refactor intentionally preserves CSS class names, endpoint paths, local-storage keys and translation keys.

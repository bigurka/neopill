export const styles = `
  :host {
    display: block;
    height: 100%;
    box-sizing: border-box;
    font-family: var(--paper-font-body1_-_font-family, "Segoe UI", Roboto, Arial, sans-serif);
    color: var(--primary-text-color, #e8eaf0);
    background: var(--primary-background-color, #111318);
  }
  * { box-sizing: border-box; }
  a { color: inherit; }

  .header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 20px;
    border-bottom: 1px solid var(--divider-color, #2a2e3a);
  }
  .header .pill-logo { width: 32px; height: 32px; flex: none; }
  .header h1 { font-size: 20px; margin: 0; flex: 1; }
  .header button.icon { background: none; border: none; color: inherit; cursor: pointer; font-size: 18px; }

  .layout { display: flex; height: calc(100% - 57px); }
  .sidebar {
    width: 260px;
    flex: none;
    border-right: 1px solid var(--divider-color, #2a2e3a);
    overflow-y: auto;
    padding: 8px;
  }
  .main { flex: 1; overflow-y: auto; padding: 16px 20px; }

  .patient-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 10px;
    border-radius: 8px;
    cursor: pointer;
    margin-bottom: 4px;
  }
  .patient-row.selected { background: rgba(29, 233, 255, 0.12); }
  .patient-row:hover { background: rgba(255, 255, 255, 0.06); }
  .patient-row .name { flex: 1; }
  .patient-row .actions { display: none; gap: 2px; }
  .patient-row:hover .actions { display: flex; }

  button {
    font: inherit;
    cursor: pointer;
    border-radius: 8px;
    border: 1px solid var(--divider-color, #3a3f4d);
    background: rgba(255, 255, 255, 0.04);
    color: inherit;
    padding: 6px 12px;
  }
  button:hover { background: rgba(255, 255, 255, 0.1); }
  button.primary {
    border: none;
    background: linear-gradient(135deg, #1de9ff, #0033a0);
    color: #fff;
  }
  button.danger { border-color: #a00000; color: #ff8a8a; }
  button.small { padding: 3px 8px; font-size: 12px; }
  button.iconbtn {
    border: none;
    background: none;
    padding: 2px 6px;
    color: inherit;
    opacity: 0.8;
  }
  button.iconbtn:hover { opacity: 1; }
  button:disabled { opacity: 0.4; cursor: default; }

  .add-patient-row { margin-top: 8px; }
  .add-patient-row button { width: 100%; }

  .med-card {
    border: 1px solid var(--divider-color, #2a2e3a);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 12px;
    background: rgba(255, 255, 255, 0.02);
  }
  .med-card .title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .med-card .title-row .name { font-size: 16px; font-weight: 600; flex: 1; }
  .badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .badge.due { background: #ff5b5b; color: #fff; }
  .badge.low-stock { background: #ffb020; color: #221800; }

  .med-card .meta { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; opacity: 0.85; margin-bottom: 10px; }
  .med-card .meta b { color: var(--primary-text-color, #e8eaf0); font-weight: 600; }

  .med-card .action-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .med-card .restock-form { display: flex; gap: 6px; align-items: center; }
  .med-card input[type="number"] {
    width: 70px;
    padding: 5px 7px;
    border-radius: 6px;
    border: 1px solid var(--divider-color, #3a3f4d);
    background: rgba(255, 255, 255, 0.04);
    color: inherit;
  }

  dialog {
    border: 1px solid var(--divider-color, #3a3f4d);
    border-radius: 12px;
    background: var(--card-background-color, #1a1d24);
    color: inherit;
    padding: 0;
    width: min(480px, 92vw);
  }
  dialog::backdrop { background: rgba(0, 0, 0, 0.55); }
  .dialog-body { padding: 18px 20px; }
  .dialog-body h2 { margin: 0 0 14px 0; font-size: 18px; }
  .field { margin-bottom: 12px; display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 12px; opacity: 0.75; }
  .field input, .field select, .field textarea {
    padding: 7px 9px;
    border-radius: 6px;
    border: 1px solid var(--divider-color, #3a3f4d);
    background: rgba(255, 255, 255, 0.04);
    color: inherit;
    font: inherit;
  }
  .field-row { display: flex; gap: 10px; }
  .field-row .field { flex: 1; }
  .dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }

  [data-role="fixed-times-list"] { display: flex; flex-direction: column; gap: 6px; margin-bottom: 6px; }
  .time-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .time-row input[type="time"] { flex: 1; }

  .weekly-day {
    border: 1px solid var(--divider-color, #3a3f4d);
    border-radius: 8px;
    padding: 8px 10px;
    margin-bottom: 6px;
  }
  .weekly-day-toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; }
  .weekly-day-toggle input[type="checkbox"] { margin: 0; }
  [data-role="weekly-day-times"] { margin-top: 8px; padding-left: 24px; }

  .empty-state { opacity: 0.6; padding: 24px; text-align: center; }
  .error-banner {
    background: rgba(160, 0, 0, 0.25);
    border: 1px solid #a00000;
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 12px;
    font-size: 13px;
  }

  table.history { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.history th, table.history td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--divider-color, #2a2e3a); }
  section.history { margin-top: 24px; }
  section.history h3 { font-size: 14px; opacity: 0.8; }
`;

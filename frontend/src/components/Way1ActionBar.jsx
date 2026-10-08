/**
 * The entry bar.
 *
 * Copy here is what a consultant on the floor reads, so it says what the
 * buttons do rather than how the system is built: "Way 1" is our name for this
 * channel (the footer still explains it against Way 2), and the database's
 * brand name is not something anyone on the floor needs.
 *
 * Hierarchy: one primary action, the rest equal secondaries, and the two
 * controls that are not data entry - bulk upload and refresh - set apart by a
 * rule rather than by competing for colour.
 */

import React from 'react';
import { PlusCircle, UserPlus, Compass, KeyRound, UploadCloud, RefreshCw } from 'lucide-react';

const ENTRIES = [
  { tab: 'booking', label: 'New Booking', Icon: PlusCircle, primary: true,
    title: 'Create a new customer vehicle booking' },
  { tab: 'lead', label: 'New Lead', Icon: UserPlus,
    title: 'Log a customer enquiry (walk-in, tele, digital, CRM)' },
  { tab: 'testdrive', label: 'Test Drive', Icon: Compass,
    title: 'Log a customer vehicle test drive' },
  { tab: 'allotment', label: 'Allotment / Delivery', Icon: KeyRound,
    title: 'Allot a free vehicle chassis from stock to an open booking' },
];

export default function Way1ActionBar({
  onOpenDrawer,
  onOpenUpload,
  onRefresh,
  isRefreshing,
}) {
  return (
    <div className="way1-bar">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
        <span className="way1-badge-pill">Direct entry</span>
        <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-2)' }}>
          Anything recorded here joins the shared record, and the sheet redraws once it lands.
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
        {ENTRIES.map(({ tab, label, Icon, primary, title }) => (
          <button
            key={tab}
            className={`w1-btn${primary ? ' primary-btn' : ''}`}
            onClick={() => onOpenDrawer(tab)}
            title={title}
          >
            <Icon size={15} />
            <span>{label}</span>
          </button>
        ))}

        <span className="w1-divider" aria-hidden="true" />

        <button
          className="w1-btn excel-btn"
          onClick={onOpenUpload}
          title="Upload a monthly DSR workbook (Excel, CSV or TXT)"
        >
          <UploadCloud size={15} />
          <span>Upload Report</span>
        </button>

        <button
          className="w1-btn w1-quiet"
          onClick={onRefresh}
          disabled={isRefreshing}
          title="Pull the latest figures"
        >
          {/* `spin` is defined in index.css. This carried Tailwind's
              `animate-spin`, which this project does not load, so the icon
              never actually turned while a refresh was running. */}
          <RefreshCw size={14} style={isRefreshing ? { animation: 'spin 0.9s linear infinite' } : undefined} />
          <span>{isRefreshing ? 'Refreshing' : 'Refresh'}</span>
        </button>
      </div>
    </div>
  );
}

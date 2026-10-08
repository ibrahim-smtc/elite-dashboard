import { useEffect } from 'react';

const SITE_ID = import.meta.env.VITE_PERFOX_SITE_ID;
// Fixed per the elite-motors Perfox workspace; only the per-agent Site ID varies.
const WIDGET_SRC = 'https://elite-motors-api.perfox.ai/widget/v1/widget.js';

/**
 * Boots the Perfox "Dashboard Insights" agent's web-chat widget. Mounted once
 * in App.jsx's shell, outside the scrollable sections, so it survives every
 * tab switch. Renders nothing until VITE_PERFOX_SITE_ID is set - the Site ID
 * only exists once the agent's Web Chat trigger has been created in Perfox
 * Studio, which is a manual step (see PERFOX_API_GUIDE.md).
 */
export default function ChatWidget() {
  useEffect(() => {
    if (!SITE_ID) return undefined;

    window.Perfox = window.Perfox || function perfoxQueue(...args) {
      (window.Perfox.q = window.Perfox.q || []).push(args);
    };

    const script = document.createElement('script');
    script.src = WIDGET_SRC;
    script.dataset.site = SITE_ID;
    script.defer = true;
    document.body.appendChild(script);

    return () => {
      document.body.removeChild(script);
    };
  }, []);

  return null;
}

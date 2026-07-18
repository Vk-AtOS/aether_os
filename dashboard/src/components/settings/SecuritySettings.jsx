import React from 'react';
import { Shield, Users, Copy, RefreshCw } from 'lucide-react';

// ── SSO / SAML Configuration Panel ────────────────────────────────────────────
export const SSOPanel = ({ ssoRef, ssoConfig, setSsoConfig, ssoForm, setSsoForm, ssoStatus, setSsoStatus }) => (
  <section id="sso" ref={ssoRef} className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <Shield className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">SSO / SAML Configuration</h3>
      {ssoConfig?.configured && (
        <span className="ml-3 text-[10px] font-bold bg-success/20 text-success border border-success/30 px-2 py-0.5 rounded uppercase tracking-wider">Active</span>
      )}
    </div>
    <div className="p-6 space-y-4">
      {ssoConfig?.configured && (
        <div className="p-3 rounded-lg bg-success/5 border border-success/20 text-xs text-muted space-y-1">
          <div><span className="font-bold text-bright">Entity ID: </span>{ssoConfig.idp_entity_id}</div>
          <div><span className="font-bold text-bright">SSO URL: </span>{ssoConfig.idp_sso_url}</div>
          <div><span className="font-bold text-bright">Certificate: </span>{ssoConfig.idp_cert_preview}</div>
        </div>
      )}
      <div className="space-y-3">
        <div>
          <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">IdP Entity ID</label>
          <input
            type="text"
            placeholder="https://idp.example.com/metadata"
            value={ssoForm.idp_entity_id}
            onChange={e => setSsoForm(f => ({ ...f, idp_entity_id: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent"
          />
        </div>
        <div>
          <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">IdP SSO URL</label>
          <input
            type="url"
            placeholder="https://idp.example.com/sso"
            value={ssoForm.idp_sso_url}
            onChange={e => setSsoForm(f => ({ ...f, idp_sso_url: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent"
          />
        </div>
        <div>
          <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">X.509 Certificate (PEM, no headers)</label>
          <textarea
            rows={4}
            placeholder="MIIDdDCCAlygAwIBAgIGA..."
            value={ssoForm.idp_cert}
            onChange={e => setSsoForm(f => ({ ...f, idp_cert: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-xs text-bright font-mono focus:outline-none focus:border-accent resize-none"
          />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={async () => {
            if (!ssoForm.idp_entity_id || !ssoForm.idp_sso_url || !ssoForm.idp_cert) return;
            setSsoStatus('saving');
            try {
              // Import api lazily to avoid circular dep if this file is loaded standalone
              const { api } = await import('../../api');
              await api.client.put('/settings/sso', ssoForm);
              setSsoConfig(c => ({ ...c, configured: true, idp_entity_id: ssoForm.idp_entity_id, idp_sso_url: ssoForm.idp_sso_url }));
              setSsoStatus('saved');
              setTimeout(() => setSsoStatus(null), 2500);
            } catch { setSsoStatus('error'); setTimeout(() => setSsoStatus(null), 3000); }
          }}
          className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
          disabled={ssoStatus === 'saving'}
        >
          {ssoStatus === 'saving' ? '...' : ssoStatus === 'saved' ? '✓ Saved' : ssoStatus === 'error' ? '✗ Error' : 'Save SSO Config'}
        </button>
        {ssoConfig?.configured && (
          <button
            onClick={async () => {
              if (!window.confirm('Remove SSO configuration? Users will no longer be able to sign in with SSO.')) return;
              setSsoStatus('deleting');
              try {
                const { api } = await import('../../api');
                await api.client.delete('/settings/sso');
                setSsoConfig({ configured: false });
                setSsoForm({ idp_entity_id: '', idp_sso_url: '', idp_cert: '' });
                setSsoStatus(null);
              } catch { setSsoStatus('error'); setTimeout(() => setSsoStatus(null), 3000); }
            }}
            className="text-[10px] font-bold bg-danger/10 text-danger border border-danger/20 px-3 py-1 rounded uppercase tracking-wider hover:bg-danger/20 transition-colors"
          >
            {ssoStatus === 'deleting' ? '...' : 'Remove SSO'}
          </button>
        )}
      </div>
    </div>
  </section>
);

// ── SCIM 2.0 Provisioning Panel ───────────────────────────────────────────────
export const SCIMPanel = ({
  scimConfig,
  scimRotateStatus,
  scimNewToken,
  setScimNewToken,
  onRotate,
}) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
      <div className="flex items-center">
        <Users className="w-4 h-4 mr-2 text-accent" />
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">SCIM 2.0 Provisioning</h3>
      </div>
      {scimConfig.configured && (
        <span className="text-[10px] font-bold bg-success/20 text-success border border-success/30 px-2 py-0.5 rounded uppercase tracking-wider">Active</span>
      )}
    </div>
    <div className="p-6 space-y-4">
      <p className="text-xs text-muted">
        Use SCIM 2.0 to automatically provision and deprovision users from your Identity Provider (Okta, Azure AD, Google Workspace, etc.).
        Configure a dedicated provisioning Bearer token below — do not use your user JWT.
      </p>
      <div className="space-y-3">
        <div>
          <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">SCIM Base URL</label>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-surface border border-border rounded px-3 py-2 text-xs font-mono text-accent break-all">
              {window.location.origin}/api/scim/v2
            </code>
            <button
              onClick={() => navigator.clipboard.writeText(`${window.location.origin}/api/scim/v2`)}
              className="shrink-0 p-2 text-muted hover:text-bright transition-colors border border-border rounded"
              title="Copy endpoint URL"
            >
              <Copy className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        <div>
          <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">
            Provisioning Token
            {scimConfig.token_source === 'env' && (
              <span className="ml-2 text-yellow-400 font-normal normal-case">— set via SCIM_BEARER_TOKEN env var</span>
            )}
            {scimConfig.token_source === 'database' && (
              <span className="ml-2 text-success font-normal normal-case">— managed in database</span>
            )}
          </label>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-surface border border-border rounded px-3 py-2 text-xs font-mono text-muted">
              {scimConfig.token_masked || 'No token configured'}
            </code>
            <button
              onClick={onRotate}
              disabled={scimRotateStatus === 'rotating'}
              className="shrink-0 flex items-center gap-1.5 text-[10px] font-bold px-3 py-2 rounded border border-border text-muted hover:text-bright hover:border-bright transition-colors disabled:opacity-50"
              title="Generate a new SCIM token"
            >
              <RefreshCw className={`w-3 h-3 ${scimRotateStatus === 'rotating' ? 'animate-spin' : ''}`} />
              {scimRotateStatus === 'rotating' ? 'Rotating…' : scimRotateStatus === 'done' ? '✓ Rotated' : scimRotateStatus === 'error' ? '✗ Error' : 'Rotate'}
            </button>
          </div>
          {scimNewToken && (
            <div className="mt-2 p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg space-y-2">
              <p className="text-[10px] font-bold text-yellow-400 uppercase tracking-wider">New token — copy now, will not be shown again</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-surface border border-border rounded px-3 py-2 text-xs font-mono text-bright break-all">{scimNewToken}</code>
                <button
                  onClick={() => navigator.clipboard.writeText(scimNewToken)}
                  className="shrink-0 p-2 text-muted hover:text-bright transition-colors border border-border rounded"
                  title="Copy token"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="text-[10px] text-muted">Paste this into your IdP provisioning settings, then dismiss.</p>
              <button onClick={() => setScimNewToken(null)} className="text-[10px] text-muted hover:text-bright underline">Dismiss</button>
            </div>
          )}
        </div>
        <div className="p-3 rounded-lg bg-surface border border-border text-xs text-muted space-y-1">
          <p className="font-bold text-bright text-[10px] uppercase tracking-wider mb-2">Supported Endpoints</p>
          <div className="font-mono space-y-0.5">
            <div><span className="text-success">GET</span>    /api/scim/v2/Users</div>
            <div><span className="text-success">GET</span>    /api/scim/v2/Users/&#123;id&#125;</div>
            <div><span className="text-accent">POST</span>   /api/scim/v2/Users</div>
            <div><span className="text-yellow-400">PUT</span>    /api/scim/v2/Users/&#123;id&#125;</div>
            <div><span className="text-danger">DELETE</span> /api/scim/v2/Users/&#123;id&#125;</div>
          </div>
        </div>
      </div>
    </div>
  </section>
);

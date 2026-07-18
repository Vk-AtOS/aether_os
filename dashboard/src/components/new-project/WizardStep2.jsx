import React from 'react';
import { PillGroup } from './WizardShared';

// ── Step 2: Guided questionnaire ───────────────────────────────────────────────
const WizardStep2 = ({
  name, setName,
  wizardAnswers, setWizardAnswers,
  uploading, uploadFilename, uploadError, fileInputRef, handleFileUpload,
  projectMode,
  repoType, setRepoType, repoUrl, setRepoUrl, repoToken, setRepoToken,
  repoSshKey, setRepoSshKey, gitlabUrl, setGitlabUrl,
  fetchingRepo, handleFetchRepo, repoFetched,
  domain, setDomain,
  schemaOpen, setSchemaOpen, schemaConnStr, setSchemaConnStr,
  importingSchema, handleImportSchema, importedSchema, schemaError,
}) => (
  <div className="space-y-6">
    <div>
      <h2 className="text-base font-semibold text-bright">Tell us about your project</h2>
      <p className="text-xs text-muted mt-1">Answer a few questions so AetherOS can build exactly what you need.</p>
    </div>

    {/* Project name */}
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">
        Project Name <span className="text-slate-500 font-normal normal-case">(optional)</span>
      </label>
      <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. TaskFlow"
        className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent" />
    </div>

    {/* Q1: Who uses it */}
    <div className="space-y-2">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">1. Who uses this app?</label>
      <PillGroup
        options={[['internal', '👥 Internal team'], ['customers', '🌐 Our customers'], ['both', '🔀 Both']]}
        value={wizardAnswers.who}
        onChange={val => setWizardAnswers(a => ({ ...a, who: a.who === val ? '' : val }))}
      />
    </div>

    {/* Q2: Scale */}
    <div className="space-y-2">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">2. Expected scale</label>
      <PillGroup
        options={[['small', '🏠 Under 100 users'], ['medium', '🏢 100–10,000 users'], ['large', '🏙️ 10,000+ users']]}
        value={wizardAnswers.scale}
        onChange={val => setWizardAnswers(a => ({ ...a, scale: a.scale === val ? '' : val }))}
      />
    </div>

    {/* Q3: Handles payments */}
    <div className="space-y-2">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">3. Handles payments?</label>
      <PillGroup
        options={[[true, '💳 Yes'], [false, '✕ No']]}
        value={wizardAnswers.money}
        onChange={val => setWizardAnswers(a => ({ ...a, money: val }))}
      />
    </div>

    {/* Q4: Industry */}
    <div className="space-y-2">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">4. Industry / Compliance</label>
      <PillGroup
        options={[
          ['general', '🌐 General'],
          ['healthcare', '🏥 Healthcare (HIPAA)'],
          ['finance', '💳 Finance (PCI/SOC2)'],
          ['government', '🏛️ Government'],
          ['education', '🎓 Education'],
        ]}
        value={wizardAnswers.industry}
        onChange={val => setWizardAnswers(a => ({ ...a, industry: val }))}
      />
    </div>

    {/* Q5: Platform */}
    <div className="space-y-2">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">5. Platform / Device</label>
      <PillGroup
        options={[['desktop', '🖥️ Desktop only'], ['responsive', '📱 Responsive web'], ['mobile', '📲 Mobile-first']]}
        value={wizardAnswers.mobile}
        onChange={val => setWizardAnswers(a => ({ ...a, mobile: a.mobile === val ? '' : val }))}
      />
    </div>

    {/* Q6: Main problem (required) */}
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">
        6. What problem does this solve? <span className="text-danger">*</span>
      </label>
      <textarea
        value={wizardAnswers.problem}
        onChange={e => setWizardAnswers(a => ({ ...a, problem: e.target.value }))}
        rows={3}
        placeholder="e.g. Our sales team tracks leads in spreadsheets — we need a CRM to manage pipeline, contacts, and follow-ups."
        className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent resize-none"
      />
    </div>

    {/* Q7: Must-have features (optional) */}
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">
        7. Must-have features <span className="text-slate-500 font-normal normal-case">(optional)</span>
      </label>
      <textarea
        value={wizardAnswers.features}
        onChange={e => setWizardAnswers(a => ({ ...a, features: e.target.value }))}
        rows={2}
        placeholder="e.g. CSV import, email notifications, role-based access, PDF exports, mobile app…"
        className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent resize-none"
      />
    </div>

    {/* File import */}
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted">Have a requirements doc?</span>
      <button onClick={() => fileInputRef.current?.click()} disabled={uploading}
        className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-bright rounded-md transition-colors disabled:opacity-50">
        {uploading ? 'Reading…' : '📄 Import file'}
      </button>
      {uploadFilename && <span className="text-[10px] text-emerald-400">📎 {uploadFilename}</span>}
      <input ref={fileInputRef} type="file" accept=".txt,.md,.pdf,.docx,.rst" className="hidden" onChange={handleFileUpload} />
    </div>
    {uploadError && <p className="text-xs text-danger">{uploadError}</p>}

    {/* Existing codebase section */}
    {projectMode === 'existing' && (
      <div className="space-y-3 bg-surface border border-border rounded-xl p-4">
        <p className="text-xs font-semibold text-muted uppercase tracking-wider">Connect Existing Codebase</p>
        <div className="flex gap-2">
          {[['github','GitHub'],['gitlab','GitLab'],['ssh','SSH']].map(([t,label]) => (
            <button key={t} onClick={() => setRepoType(t)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors border ${repoType === t ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>
              {label}
            </button>
          ))}
        </div>
        {repoType === 'gitlab' && (
          <input type="url" value={gitlabUrl} onChange={e => setGitlabUrl(e.target.value)}
            placeholder="https://gitlab.com (or self-hosted URL)"
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
        )}
        <input type={repoType === 'ssh' ? 'text' : 'url'} value={repoUrl} onChange={e => setRepoUrl(e.target.value)}
          placeholder={repoType === 'ssh' ? 'git@github.com:owner/repo.git' : `https://${repoType === 'gitlab' ? 'gitlab.com' : 'github.com'}/owner/repo`}
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
        {repoType !== 'ssh' ? (
          <input type="password" value={repoToken} onChange={e => setRepoToken(e.target.value)}
            placeholder={`${repoType === 'gitlab' ? 'GitLab' : 'GitHub'} Personal Access Token (private repos)`}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
        ) : (
          <textarea value={repoSshKey} onChange={e => setRepoSshKey(e.target.value)} rows={4}
            placeholder="Paste your PEM private SSH key (-----BEGIN OPENSSH PRIVATE KEY-----)"
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-xs text-bright font-mono focus:outline-none focus:border-accent resize-none" />
        )}
        <button onClick={handleFetchRepo} disabled={fetchingRepo || !repoUrl.trim()}
          className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
          {fetchingRepo ? 'Fetching…' : 'Fetch Repo Context'}
        </button>
        {repoFetched && <p className="text-xs text-emerald-400">✅ Loaded context from {repoFetched}</p>}
      </div>
    )}

    {/* Domain — auto-set but still editable */}
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-muted uppercase tracking-wider">
        Domain <span className="text-slate-500 font-normal normal-case">(auto-detected from industry)</span>
      </label>
      <select value={domain} onChange={e => setDomain(e.target.value)}
        className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright focus:outline-none focus:border-accent">
        {['general','saas','fintech','healthcare','ecommerce','analytics','education','iot','marketplace','social','api','cms','erp'].map(d => (
          <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
        ))}
      </select>
    </div>

    {/* Import existing schema */}
    <div className="border border-border rounded-xl overflow-hidden">
      <button type="button" onClick={() => setSchemaOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface/80 transition-colors text-left">
        <span className="text-xs font-semibold text-muted uppercase tracking-wider">
          Import existing schema
          {importedSchema && (
            <span className="ml-2 normal-case text-emerald-400 font-normal">
              — {importedSchema.tables.length} table{importedSchema.tables.length !== 1 ? 's' : ''} imported
            </span>
          )}
        </span>
        <span className="text-muted text-xs">{schemaOpen ? '▲' : '▼'}</span>
      </button>
      {schemaOpen && (
        <div className="px-4 pb-4 pt-3 space-y-3 bg-bg border-t border-border">
          <p className="text-xs text-muted">
            Point at an existing PostgreSQL, MySQL, or SQLite database. AetherOS will read its schema
            and feed it into the architecture phase instead of generating one from scratch.
          </p>
          <input type="password" value={schemaConnStr} onChange={e => setSchemaConnStr(e.target.value)}
            placeholder="postgresql://user:pass@host:5432/dbname"
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-mono placeholder:text-muted/50 focus:outline-none focus:border-accent" />
          <div className="flex items-center gap-3">
            <button type="button" onClick={handleImportSchema} disabled={importingSchema || !schemaConnStr.trim()}
              className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
              {importingSchema ? 'Connecting…' : 'Test & Import'}
            </button>
            {importedSchema && !schemaError && (
              <span className="text-xs text-emerald-400">
                {importedSchema.tables.length} table{importedSchema.tables.length !== 1 ? 's' : ''} detected
                {importedSchema.tables.length > 0 && ` (${importedSchema.tables.map(t => t.name).slice(0, 4).join(', ')}${importedSchema.tables.length > 4 ? '…' : ''})`}
              </span>
            )}
          </div>
          {schemaError && <p className="text-xs text-danger">{schemaError}</p>}
        </div>
      )}
    </div>
  </div>
);

export default WizardStep2;

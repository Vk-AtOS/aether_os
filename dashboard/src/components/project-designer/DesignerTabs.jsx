import React from 'react';
import { Upload, ChevronDown, Check, Loader2, ChevronRight, Database } from 'lucide-react';
import {
  TEMPLATES, COUNTRIES, REGION_COMPLIANCE, EMBARGOED,
  UI_THEMES, LAYOUTS, FONT_PAIRS, COLOR_SLOTS,
} from './DesignerData';
import { HslPicker } from './DesignerComponents';

// ── UnderstandTab ─────────────────────────────────────────────────────────────
export const UnderstandTab = ({
  selectedTemplate, applyTemplate,
  projectMode, setProjectMode,
  projectName, setProjectName,
  domain, setDomain,
  requirement, setRequirement,
  uploadFilename, uploading, uploadError, fileInputRef, handleFileUpload,
  repoType, setRepoType, repoUrl, setRepoUrl, repoToken, setRepoToken,
  repoSshKey, setRepoSshKey, gitlabUrl, setGitlabUrl,
  fetchingRepo, handleFetchRepo, repoFetched,
  schemaOpen, setSchemaOpen, schemaConnStr, setSchemaConnStr,
  importingSchema, handleImportSchema, importedSchema, schemaError,
}) => (
  <div className="space-y-7">
    {/* Template grid */}
    <div>
      <p className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Quick Start — pick a template</p>
      <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
        {TEMPLATES.map(tpl => (
          <button key={tpl.id} type="button" onClick={() => applyTemplate(tpl)}
            className={`flex flex-col items-center gap-1 p-3 rounded-xl border text-xs font-semibold transition-all ${
              selectedTemplate === tpl.id ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-bright'
            }`}>
            <span className="text-xl">{tpl.icon}</span>
            <span className="leading-tight text-center">{tpl.label}</span>
          </button>
        ))}
      </div>
    </div>

    <div className="h-px bg-border" />

    {/* Mode toggle */}
    <div>
      <p className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Build mode</p>
      <div className="flex gap-3">
        {[['new','✨','Start fresh'],['existing','🔗','Improve existing codebase']].map(([mode,icon,label]) => (
          <button key={mode} type="button" onClick={() => setProjectMode(mode)}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border text-sm font-semibold transition-all ${
              projectMode === mode ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40'
            }`}>
            <span>{icon}</span><span>{label}</span>
          </button>
        ))}
      </div>
    </div>

    {/* Name + requirement */}
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <div className="sm:col-span-1">
        <label className="block text-xs font-bold text-muted uppercase tracking-widest mb-1.5">Project Name</label>
        <input className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors"
          placeholder="My Awesome App" value={projectName} onChange={e => setProjectName(e.target.value)} />
      </div>
      <div className="sm:col-span-2">
        <label className="block text-xs font-bold text-muted uppercase tracking-widest mb-1.5">Domain</label>
        <select value={domain} onChange={e => setDomain(e.target.value)}
          className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors">
          {TEMPLATES.map(t => <option key={t.domain} value={t.domain}>{t.icon} {t.label}</option>)}
        </select>
      </div>
    </div>

    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs font-bold text-muted uppercase tracking-widest">
          Requirement <span className="text-red-400">*</span>
        </label>
        <div className="flex items-center gap-2">
          {uploadFilename && <span className="text-[10px] text-emerald-400">📎 {uploadFilename}</span>}
          <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading}
            className="text-[10px] px-2.5 py-1 bg-surface hover:bg-border border border-border text-muted hover:text-bright rounded-md transition-colors disabled:opacity-50">
            {uploading ? <Loader2 className="w-3 h-3 animate-spin inline" /> : <Upload className="w-3 h-3 inline mr-1" />}
            {uploading ? 'Reading…' : 'Import file'}
          </button>
          <input ref={fileInputRef} type="file" accept=".txt,.md,.pdf,.docx,.rst" className="hidden" onChange={handleFileUpload} />
        </div>
      </div>
      <textarea value={requirement} onChange={e => setRequirement(e.target.value)} rows={7}
        placeholder="Describe what you want to build in detail. Include user stories, key features, integrations, and any constraints…"
        className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-accent transition-colors resize-none" />
      {uploadError && <p className="text-xs text-red-400 mt-1">{uploadError}</p>}
      <p className="text-xs text-muted mt-1">{requirement.length} characters</p>
    </div>

    {/* Existing codebase section */}
    {projectMode === 'existing' && (
      <div className="space-y-3 bg-surface border border-border rounded-xl p-4">
        <p className="text-xs font-bold text-muted uppercase tracking-widest">Connect Existing Codebase</p>
        <div className="flex gap-2">
          {[['github','GitHub'],['gitlab','GitLab'],['ssh','SSH']].map(([t,label]) => (
            <button key={t} type="button" onClick={() => setRepoType(t)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-colors ${repoType === t ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>
              {label}
            </button>
          ))}
        </div>
        {repoType === 'gitlab' && (
          <input type="url" value={gitlabUrl} onChange={e => setGitlabUrl(e.target.value)}
            placeholder="https://gitlab.com (or self-hosted)"
            className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
        )}
        <input type={repoType === 'ssh' ? 'text' : 'url'} value={repoUrl} onChange={e => setRepoUrl(e.target.value)}
          placeholder={repoType === 'ssh' ? 'git@github.com:owner/repo.git' : `https://${repoType === 'gitlab' ? 'gitlab.com' : 'github.com'}/owner/repo`}
          className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
        {repoType !== 'ssh' ? (
          <input type="password" value={repoToken} onChange={e => setRepoToken(e.target.value)}
            placeholder={`${repoType === 'gitlab' ? 'GitLab' : 'GitHub'} Personal Access Token (private repos)`}
            className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
        ) : (
          <textarea value={repoSshKey} onChange={e => setRepoSshKey(e.target.value)} rows={4}
            placeholder="Paste PEM private SSH key (-----BEGIN OPENSSH PRIVATE KEY-----)"
            className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-xs text-bright font-mono focus:outline-none focus:border-accent resize-none" />
        )}
        <div className="flex items-center gap-3">
          <button type="button" onClick={handleFetchRepo} disabled={fetchingRepo || !repoUrl.trim()}
            className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
            {fetchingRepo ? 'Fetching…' : 'Fetch Repo Context'}
          </button>
          {repoFetched && <p className="text-xs text-emerald-400">✅ Loaded from {repoFetched}</p>}
        </div>
      </div>
    )}

    {/* Schema import */}
    <div className="border border-border rounded-xl overflow-hidden">
      <button type="button" onClick={() => setSchemaOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface/80 transition-colors text-left">
        <span className="flex items-center gap-2 text-xs font-bold text-muted uppercase tracking-widest">
          <Database className="w-3.5 h-3.5" />
          Import existing schema
          {importedSchema && <span className="normal-case text-emerald-400 font-normal">— {importedSchema.tables?.length} tables imported</span>}
        </span>
        {schemaOpen ? <ChevronDown className="w-4 h-4 text-muted" /> : <ChevronRight className="w-4 h-4 text-muted" />}
      </button>
      {schemaOpen && (
        <div className="px-4 pb-4 pt-3 space-y-3 border-t border-border bg-panel">
          <p className="text-xs text-muted">Connect a PostgreSQL, MySQL, or SQLite database — AetherOS reads the schema and feeds it into the architecture phase.</p>
          <input type="password" value={schemaConnStr} onChange={e => setSchemaConnStr(e.target.value)}
            placeholder="postgresql://user:pass@host:5432/dbname"
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-mono focus:outline-none focus:border-accent" />
          <div className="flex items-center gap-3">
            <button type="button" onClick={handleImportSchema} disabled={importingSchema || !schemaConnStr.trim()}
              className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
              {importingSchema ? 'Connecting…' : 'Test & Import'}
            </button>
            {importedSchema && !schemaError && (
              <span className="text-xs text-emerald-400">✅ {importedSchema.tables?.length} tables ready</span>
            )}
            {schemaError && <span className="text-xs text-red-400">{schemaError}</span>}
          </div>
        </div>
      )}
    </div>
  </div>
);

// ── DesignTab ──────────────────────────────────────────────────────────────────
export const DesignTab = ({ spec, updateSpec, activeColorSlot, setActiveColorSlot }) => (
  <div className="space-y-8">
    {/* ── Style Foundation ── */}
    <div>
      <div className="flex items-baseline gap-2 mb-1">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Style Foundation</h3>
        <span className="text-[10px] text-muted normal-case">— pick a base, then customise everything below</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {UI_THEMES.map(theme => (
          <button key={theme.id} type="button" onClick={() => updateSpec('design', 'ui_theme', theme.id)}
            className={`group relative flex flex-col rounded-xl border-2 overflow-hidden transition-all ${
              spec.design.ui_theme === theme.id ? 'border-accent shadow-lg shadow-accent/20 scale-[1.02]' : 'border-border hover:border-accent/40'
            }`}>
            <div className="w-full aspect-[3/2] bg-panel overflow-hidden">{theme.preview}</div>
            <div className={`px-2 py-1.5 text-left ${spec.design.ui_theme === theme.id ? 'bg-accent/10' : 'bg-surface'}`}>
              <div className="flex items-center justify-between">
                <span className={`text-[11px] font-bold ${spec.design.ui_theme === theme.id ? 'text-accent' : 'text-bright'}`}>{theme.label}</span>
                {spec.design.ui_theme === theme.id && <Check className="w-3 h-3 text-accent shrink-0" />}
              </div>
            </div>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-panel border border-border rounded-lg text-[10px] text-bright opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50 shadow-xl max-w-[180px] text-center leading-relaxed whitespace-normal">
              {theme.description}
            </div>
          </button>
        ))}
      </div>
    </div>

    <div className="h-px bg-border" />

    {/* ── Animations & Motion ── */}
    <div>
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-4">Animations & Motion</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        <div>
          <label className="block text-xs text-muted mb-1.5">Page Transitions</label>
          <div className="grid grid-cols-2 gap-1.5">
            {[
              {id:'none',label:'None',desc:'Instant'},{id:'fade',label:'Fade',desc:'Crossfade'},
              {id:'slide',label:'Slide',desc:'Horizontal push'},{id:'scale',label:'Scale',desc:'Zoom in/out'},
              {id:'flip',label:'Flip',desc:'3D flip'},{id:'blur',label:'Blur',desc:'Defocus shift'},
            ].map(t => (
              <button key={t.id} type="button" onClick={() => updateSpec('design','page_transition',t.id)}
                className={`flex flex-col px-2 py-2 rounded-lg border text-left transition-all ${spec.design.page_transition === t.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'}`}>
                <span className={`text-xs font-semibold ${spec.design.page_transition === t.id ? 'text-accent' : 'text-bright'}`}>{t.label}</span>
                <span className="text-[10px] text-muted">{t.desc}</span>
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Animation Speed</label>
          <div className="grid grid-cols-2 gap-1.5 mb-4">
            {[
              {id:'instant',label:'Instant',css:'0ms'},{id:'fast',label:'Fast',css:'150ms'},
              {id:'normal',label:'Normal',css:'300ms'},{id:'slow',label:'Slow',css:'500ms'},
              {id:'cinematic',label:'Cinematic',css:'800ms'},
            ].map(s => (
              <button key={s.id} type="button" onClick={() => updateSpec('design','animation_speed',s.id)}
                className={`flex items-center justify-between px-2 py-2 rounded-lg border text-xs transition-all ${spec.design.animation_speed === s.id ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-bright'}`}>
                <span className="font-semibold">{s.label}</span>
                <span className="text-[10px] opacity-60">{s.css}</span>
              </button>
            ))}
          </div>
          <label className="block text-xs text-muted mb-1.5">Loading Skeleton</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['none','pulse','shimmer'].map(l => (
              <button key={l} type="button" onClick={() => updateSpec('design','loading_style',l)}
                className={`py-2 text-xs font-semibold capitalize rounded-lg border transition-all ${spec.design.loading_style === l ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{l}</button>
            ))}
          </div>
        </div>
        <div className="space-y-3">
          <label className="block text-xs text-muted">Interaction Effects</label>
          {[
            {key:'micro_interactions',label:'Micro-interactions',desc:'Button press, ripple, tick feedback'},
            {key:'scroll_reveal',label:'Scroll reveal',desc:'Elements animate in as you scroll'},
            {key:'hover_lift',label:'Hover lift',desc:'Cards rise on hover (translateY + shadow)'},
          ].map(f => (
            <button key={f.key} type="button" onClick={() => updateSpec('design', f.key, !spec.design[f.key])}
              className={`w-full flex items-start gap-3 p-3 rounded-xl border text-left transition-all ${spec.design[f.key] ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/30'}`}>
              <div className={`mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors ${spec.design[f.key] ? 'border-accent bg-accent' : 'border-border'}`}>
                {spec.design[f.key] && <Check className="w-2.5 h-2.5 text-white" />}
              </div>
              <div>
                <p className={`text-xs font-semibold ${spec.design[f.key] ? 'text-accent' : 'text-bright'}`}>{f.label}</p>
                <p className="text-[10px] text-muted mt-0.5">{f.desc}</p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>

    <div className="h-px bg-border" />

    {/* ── Colors / Typography / Layout ── */}
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Colors */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Brand Colors</h3>
        <div className="flex gap-1">
          {COLOR_SLOTS.map(slot => (
            <button key={slot} type="button" onClick={() => setActiveColorSlot(slot)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded capitalize transition-all ${activeColorSlot === slot ? 'bg-accent text-white' : 'bg-surface border border-border text-muted hover:text-bright'}`}>
              {slot}
            </button>
          ))}
        </div>
        <HslPicker hex={spec.design[activeColorSlot]} onChange={v => updateSpec('design', activeColorSlot, v)} />
        <div className="flex gap-2">
          {COLOR_SLOTS.map(slot => (
            <div key={slot} className="flex-1 flex flex-col items-center gap-1">
              <div onClick={() => setActiveColorSlot(slot)}
                className={`w-full h-8 rounded-lg cursor-pointer border-2 transition-all ${activeColorSlot === slot ? 'border-white' : 'border-transparent'}`}
                style={{ background: spec.design[slot] }} />
              <span className="text-[9px] text-muted capitalize">{slot}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Typography */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Typography</h3>
        <div>
          <label className="block text-xs text-muted mb-2">Font Pairing</label>
          {FONT_PAIRS.map(fp => (
            <button key={fp} type="button" onClick={() => updateSpec('design','font_pairing',fp)}
              className={`w-full flex items-center justify-between px-3 py-2.5 mb-1.5 rounded-lg border text-xs transition-all ${spec.design.font_pairing === fp ? 'border-accent bg-accent/10 text-accent' : 'border-border text-bright hover:border-accent/40'}`}>
              {fp}{spec.design.font_pairing === fp && <Check className="w-3.5 h-3.5" />}
            </button>
          ))}
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Font Size Scale</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['Compact','Normal','Comfortable'].map(s => (
              <button key={s} type="button" onClick={() => updateSpec('design','font_scale',s)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.font_scale === s ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{s}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Border Radius</label>
          <div className="grid grid-cols-2 gap-1.5">
            {['Sharp (0px)','Subtle (4px)','Rounded (8px)','Pill (16px)'].map(r => (
              <button key={r} type="button" onClick={() => updateSpec('design','border_radius',r)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.border_radius === r ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{r}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Layout */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Layout & Structure</h3>
        <div className="space-y-2">
          {LAYOUTS.map(lay => (
            <button key={lay.id} type="button" onClick={() => updateSpec('design','layout',lay.id)}
              className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all ${spec.design.layout === lay.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'}`}>
              <div className="w-16 h-10 shrink-0 rounded overflow-hidden border border-border/50">{lay.svg}</div>
              <span className={`text-xs font-semibold flex-1 text-left ${spec.design.layout === lay.id ? 'text-accent' : 'text-bright'}`}>{lay.label}</span>
              {spec.design.layout === lay.id && <Check className="w-4 h-4 text-accent" />}
            </button>
          ))}
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Component Density</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['Compact','Normal','Spacious'].map(d => (
              <button key={d} type="button" onClick={() => updateSpec('design','density',d)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.density === d ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{d}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Card Style</label>
          <div className="grid grid-cols-2 gap-1.5">
            {['Flat','Subtle Shadow','Elevated','Glass'].map(cs => (
              <button key={cs} type="button" onClick={() => updateSpec('design','card_style',cs)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.card_style === cs ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{cs}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  </div>
);

// ── ComplianceTab ─────────────────────────────────────────────────────────────
export const ComplianceTab = ({ spec, updateSpec, countrySearch, setCountrySearch }) => {
  const cc = spec.compliance;
  const selectedCountry = COUNTRIES.find(c => c.code === cc.production_country);
  const region = selectedCountry?.region || 'global';
  const frameworks = REGION_COMPLIANCE[region] || REGION_COMPLIANCE.global;
  const isEmbargoed = EMBARGOED.has(cc.production_country);
  const isEU = region === 'EU' || region === 'UK';
  const filtered = COUNTRIES.filter(c =>
    c.label.toLowerCase().includes(countrySearch.toLowerCase()) ||
    c.code.toLowerCase().includes(countrySearch.toLowerCase())
  );
  return (
    <div className="space-y-7">
      {/* Country selector */}
      <div>
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-1">Production Country</h3>
        <p className="text-xs text-muted mb-3">Where will end users of this product be located? AetherOS will enforce the correct compliance frameworks automatically before, during, and after the build.</p>
        <input
          className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent mb-3 transition-colors"
          placeholder="Search country…" value={countrySearch} onChange={e => setCountrySearch(e.target.value)}
        />
        <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-1.5 max-h-64 overflow-y-auto custom-scrollbar pr-1">
          {filtered.map(c => (
            <button key={c.code} type="button" onClick={() => updateSpec('compliance', 'production_country', c.code)}
              className={`flex flex-col items-center gap-0.5 p-2 rounded-lg border text-xs transition-all ${
                cc.production_country === c.code ? 'border-accent bg-accent/10 text-accent'
                  : EMBARGOED.has(c.code) ? 'border-red-800/40 text-red-400/70 hover:border-red-600/60'
                  : 'border-border text-muted hover:border-accent/40 hover:text-bright'
              }`}>
              <span className="text-lg leading-none">{c.flag}</span>
              <span className="font-semibold text-[10px] leading-tight text-center">{c.label}</span>
              <span className="text-[9px] opacity-60">{c.code}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Live compliance panel */}
      {cc.production_country && (
        <div className={`rounded-xl border p-5 space-y-4 ${isEmbargoed ? 'border-red-600/50 bg-red-500/5' : 'border-accent/30 bg-accent/5'}`}>
          <div className="flex items-start gap-3">
            <span className="text-3xl">{selectedCountry?.flag}</span>
            <div>
              <h4 className="text-base font-bold text-bright">{selectedCountry?.label}
                <span className="ml-2 text-xs font-normal text-muted">({selectedCountry?.region})</span>
              </h4>
              {isEmbargoed ? (
                <div className="flex items-center gap-1.5 mt-1">
                  <div className="w-2 h-2 rounded-full bg-red-500" />
                  <span className="text-xs font-bold text-red-400">EMBARGOED JURISDICTION — Pipeline will be blocked</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 mt-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-400" />
                  <span className="text-xs text-emerald-400 font-semibold">Compliance rules will be auto-enforced</span>
                </div>
              )}
            </div>
          </div>
          <div>
            <p className="text-xs font-bold text-muted uppercase tracking-widest mb-2">Applicable Frameworks</p>
            <div className="flex flex-wrap gap-2">
              {frameworks.map(f => (
                <span key={f} className="px-2.5 py-1 bg-surface border border-border rounded-full text-xs text-bright font-medium">{f}</span>
              ))}
            </div>
          </div>
          {isEU && (
            <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-xs text-blue-300 space-y-1">
              <p className="font-bold">GDPR Requirements — automatically injected into your build:</p>
              <ul className="list-disc list-inside space-y-0.5 text-blue-300/80">
                <li>Cookie consent banner</li>
                <li>Privacy policy endpoint + GDPR data deletion API</li>
                <li>Data processing records in audit log</li>
                <li>Right to erasure implementation</li>
                <li>Data Protection Officer contact field</li>
              </ul>
            </div>
          )}
        </div>
      )}
      {!cc.production_country && (
        <div className="flex items-center gap-3 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-xl">
          <span className="text-2xl">⚠️</span>
          <p className="text-sm text-yellow-300">No country selected — compliance checks will run in generic mode. Select a country to get jurisdiction-specific enforcement.</p>
        </div>
      )}

      <div className="h-px bg-border" />

      {/* Additional compliance flags */}
      <div>
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Data Handling Flags</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-muted mb-1.5">Data Sensitivity</label>
            <div className="grid grid-cols-3 gap-1.5">
              {['low','moderate','high'].map(s => (
                <button key={s} type="button" onClick={() => updateSpec('compliance','data_sensitivity',s)}
                  className={`py-2 text-xs font-semibold rounded-lg border capitalize transition-all ${cc.data_sensitivity === s ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{s}</button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1.5">Deployment Type</label>
            <div className="grid grid-cols-3 gap-1.5">
              {['saas','on_prem','hybrid'].map(d => (
                <button key={d} type="button" onClick={() => updateSpec('compliance','deployment_type',d)}
                  className={`py-2 text-xs font-semibold rounded-lg border capitalize transition-all ${cc.deployment_type === d ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{d.replace('_',' ')}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          {[
            {key:'handles_personal_data',label:'Personal Data'},
            {key:'handles_biometric_data',label:'Biometric Data'},
            {key:'handles_children_data',label:"Children's Data"},
            {key:'requires_data_residency',label:'Data Residency Required'},
          ].map(f => (
            <div key={f.key}>
              <label className="block text-xs text-muted mb-1">{f.label}</label>
              <button type="button" onClick={() => updateSpec('compliance', f.key, !cc[f.key])}
                className={`w-full px-3 py-2 rounded-lg text-sm font-semibold border transition-all ${cc[f.key] ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-border/80'}`}>
                {cc[f.key] ? 'Yes' : 'No'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

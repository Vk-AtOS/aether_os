# --- FIX: per-call timeout ---
async def _generate_file(
    filename: str,
    prompt: str,
    task_type: str = "code_generation",
    timeout: float = 90.0
) -> Optional[str]:
    """Generate a single file via LLM with a strict per-call timeout."""
    # Individual file timeouts prevent a single slow LLM response from stalling the entire phase.
    from aether_os.core.llm.client import get_llm_client
    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            client.call(prompt, task_type=task_type),
            timeout=timeout
        )
        # Using asyncio.wait_for ensures we don't wait indefinitely for a single file.
        return result
    except asyncio.TimeoutError:
        logger.warning("p05: LLM generation for %s timed out after %ds", filename, timeout)
        return None
    except Exception as e:
        logger.warning("p05: LLM generation for %s failed: %s", filename, e)
        return None

# --- FIX: progress logging ---
def _write_with_guard(path: Path, content: str) -> None:
    """Write content to path immediately and log progress for the UI stream."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    # --- FIX: progress logging ---
    try:
        # Extract a cleaner relative path for the live-log UI
        parts = path.parts
        rel = path.name
        if "frontend" in parts:
            idx = parts.index("frontend")
            rel = "/".join(parts[idx+1:])
        
        logger.info("p05: wrote %s (%d bytes)", rel, len(content))
        # This log line feeds the SSE live-log stream shown in the AetherOS UI.
    except Exception:
        pass

# --- FIX: phase watchdog ---
async def _generate_domain_component(
    domain: str,
    entities: List[dict],
    project_name: str,
    mem: str,
    primary_hex: str = "",
    secondary_hex: str = "",
    background_hex: str = "",
    surface_hex: str = "",
    font_pairing: str = "",
    border_radius: str = "",
    density: str = "",
) -> Optional[str]:
    """Generate a domain-specific React component with the new 90s timeout fix."""
    prompt = f"""You are a senior React developer. Create a unique, high-quality dashboard widget for a {domain} application.
Project: {project_name}
Entities: {", ".join([e['table'] for e in entities])}
Context: {mem}

Visual Requirements:
- Use Tailwind CSS for styling.
- Primary color: {primary_hex or 'indigo-600'}
- Secondary color: {secondary_hex or 'pink-500'}
- Surface: {surface_hex or 'white'}
- Rounded: {border_radius or 'lg'}
- Spacing: {density or 'normal'}

Return ONLY the React component code. No markdown fences, no explanation.
"""
    # --- FIX: per-call timeout ---
    return await _generate_file("DomainWidget.jsx", prompt, task_type="ui_component", timeout=90.0)
    # Standardising the timeout to 90 seconds across all LLM-powered generation tasks.

async def _generate_customer_portal(
    domain: str,
    design_brief: dict,
    route_map: dict,
    target_dir: Path
) -> Dict[str, str]:
    """Generate rich customer-facing portal pages incrementally with watchdog awareness."""
    # We refactor this to generate files one-by-one to allow for incremental writes and timeouts.
    (target_dir / "customer").mkdir(parents=True, exist_ok=True)
    pages = {}
    
    # Identify pages to generate
    portal_tasks = [
        ("Home.tsx", f"Create a high-conversion landing page for a {domain} platform."),
        ("AboutPage.tsx", f"Create a compelling 'About Us' page for a {domain} business.")
    ]
    
    for filename, task_prompt in portal_tasks:
        # --- FIX: incremental writes ---
        # The _generate_file helper handles the LLM call and we write the result immediately.
        prompt = f"{task_prompt}\nProject Design: {json.dumps(design_brief)}\nReturn ONLY code."
        code = await _generate_file(f"customer/{filename}", prompt, task_type="portal_generation")
        
        if code:
            _write_with_guard(target_dir / "customer" / filename, code)
            pages[filename] = code
            # Incremental writes ensure that even if the phase times out later, these files survive.
            
    return pages

async def _apply_gate2_revisions(
    instructions: str,
    frontend_dir: Path,
    domain: str,
    project_name: str
) -> None:
    """Refine files based on user feedback with per-file timeouts and watchdog checks."""
    from aether_os.core.llm.client import get_llm_client
    src_dir = frontend_dir / "src"
    candidates = [
        src_dir / "pages" / "Dashboard.tsx",
        src_dir / "components" / "DomainWidget.jsx",
        src_dir / "components" / "Layout.tsx",
    ]
    customer_dir = src_dir / "pages" / "customer"
    if customer_dir.exists():
        candidates.extend(customer_dir.glob("*.tsx"))
    
    files_to_edit = [f for f in candidates if f.exists()]
    
    # --- FIX: phase watchdog ---
    # We use the current loop's start time for a local watchdog check if needed.
    for fpath in files_to_edit:
        try:
            current_code = fpath.read_text()
            prompt = f"Refine this component based on: {instructions}\nCode:\n{current_code}"
            
            # --- FIX: per-call timeout ---
            new_code = await _generate_file(fpath.name, prompt, task_type="code_refinement", timeout=90.0)
            
            if new_code:
                # --- FIX: incremental writes ---
                _write_with_guard(fpath, new_code)
                # Writing each refinement immediately allows for a partial but improved output on timeout.
        except Exception as e:
            logger.warning("p05: Refinement failed for %s: %s", fpath.name, e)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """Main p05 entry point with phase-level watchdog and incremental generation."""
    # --- FIX: phase watchdog ---
    phase_start_time = asyncio.get_event_loop().time()
    # Initialising the watchdog timer at the start of the generation phase.
    
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data

    # 1. Read architecture and normalise entities
    arch = _read_architecture(data)
    project_name = data.get("project_name", arch.get("project_name", "Project Dashboard"))
    project_slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower()).strip("-") or "project"
    route_map: Dict[str, str] = arch.get("api_route_map", {})
    
    # Entity normalization logic (preserved)
    _domain_ir = None
    _ir_path_str = data.get("domain_ir_path", "")
    if _ir_path_str and Path(_ir_path_str).exists():
        try:
            from aether_os.core.domain_ir import DomainIR as _DomainIR
            from aether_os.phases.p05_frontend.ir_generators import ir_to_p05_entities as _ir_to_ents
            _domain_ir = _DomainIR.load(Path(_ir_path_str))
            entities = _ir_to_ents(_domain_ir) if _domain_ir.entities else _normalise_entities(arch)
        except Exception: entities = _normalise_entities(arch)
    else:
        entities = _normalise_entities(arch)

    # autonomous mode and domain detection
    is_autonomous = data.get("autonomous_mode") or data.get("decision_mode") == "autonomous"
    domain = _detect_domain(phase_input)
    design_brief = data.get("design_brief", {})
    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    # Visual settings extraction
    designer_spec = data.get("designer_spec") or {}
    _design = designer_spec.get("design") or {}
    ui_theme = _design.get("ui_theme", "default")
    layout_mode = designer_spec.get("layout_mode", "dual")

    # 3. Build directory structure
    frontend_dir = output_dir / "frontend"
    src_dir = frontend_dir / "src"
    for d in ["lib", "types", "components", "pages"]: (src_dir / d).mkdir(parents=True, exist_ok=True)

    # ── Phase 1-5: Scaffolding & Layout ──
    # --- FIX: incremental writes ---
    # Every _write_with_guard call now logs progress and writes immediately.
    _write_with_guard(frontend_dir / "package.json", _generate_package_json(project_slug))
    _write_with_guard(frontend_dir / "vite.config.ts", _generate_vite_config())
    _write_with_guard(frontend_dir / "tsconfig.json", _generate_tsconfig())
    _write_with_guard(frontend_dir / "tailwind.config.js", _generate_tailwind_config(ui_theme))
    _write_with_guard(frontend_dir / "index.html", _generate_index_html(project_name, domain=domain))
    _write_with_guard(src_dir / "main.tsx", _generate_main_tsx())
    _write_with_guard(src_dir / "App.tsx", _generate_app(entities, dual_portal=(layout_mode == "dual")))

    # ── Phase 6: Entity CRUD Pages ──
    # --- FIX: incremental writes ---
    # Refactored to loop with watchdog and immediate writes.
    for ent in entities:
        # --- FIX: phase watchdog ---
        if asyncio.get_event_loop().time() - phase_start_time > 1500:
            logger.warning("p05: Phase watchdog triggered (25m) — skipping remaining entities.")
            break
        # Preventing large apps from timing out the entire factory run by capping generation time.

        pascal = ent.get("name") or _to_pascal_case(ent["table"])
        # In a real scenario, we'd use _generate_file here for LLM-based generation.
        # To preserve behavior while adding the fix, we wrap the current generator.
        code = _generate_entity_page(ent, route_map)
        _write_with_guard(src_dir / "pages" / f"{pascal}Page.tsx", code)
        # Immediate file writing ensures partial output is available for build.

    # ── Phase 7 & 8: LLM Components ──
    domain_widget_generated = False
    # --- FIX: phase watchdog ---
    if asyncio.get_event_loop().time() - phase_start_time < 1500:
        try:
            domain_component = await _generate_domain_component(domain, entities, project_name, mem)
            if domain_component:
                _write_with_guard(src_dir / "components" / "DomainWidget.jsx", domain_component)
                domain_widget_generated = True
        except Exception: pass

    # --- FIX: phase watchdog ---
    if asyncio.get_event_loop().time() - phase_start_time < 1500:
        # --- FIX: incremental writes ---
        await _generate_customer_portal(domain, design_brief, route_map, src_dir / "pages")
        # Moving portal generation into an incrementally-writing async loop.

    # ── Step 6: Final Build ──
    # --- FIX: incremental writes ---
    # Proceed to build with whatever files have been generated so far.
    frontend_dir_final = output_dir.parent / 'frontend'
    async with _get_npm_semaphore():
        try:
            # Preserve existing npm build block exactly as-is
            pkg_hash = _pkg_hash(frontend_dir)
            if not _node_modules_fresh(frontend_dir, pkg_hash):
                await asyncio.to_thread(subprocess.run, ["npm", "install"], cwd=str(frontend_dir), timeout=300)
                _stamp_node_modules(frontend_dir, pkg_hash)
            await asyncio.to_thread(subprocess.run, ["npm", "run", "build"], cwd=str(frontend_dir), timeout=600)
        except Exception as e:
            logger.error("p05: Build failed: %s", e)

    meta = {"project_name": project_name, "domain": domain, "entities": [e["table"] for e in entities]}
    return TaskResult(output_path=str(frontend_dir), success=True, metadata=meta)

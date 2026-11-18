"""P05 Frontend — file-writing / scaffold helpers.

All _generate_* functions that produce static file content for the generated
React/Vite/TanStack project live here. Each function returns a string (the
file contents to write). The run() function in task_agent.py calls these
and writes the results to disk.

(KAN-58: the generators now live in code_writer_parts/part*.py, in their original order; this module
re-exports every name, so existing imports and the public aliases below keep working.)
"""
# ruff: noqa: F401
from __future__ import annotations

import html  # noqa: F401
import json  # noqa: F401
import logging  # noqa: F401
from pathlib import Path  # noqa: F401
from typing import Any, Dict, List, Optional  # noqa: F401
from aether_os.phases.p05_frontend.scaffold import (
    EXCLUDED_COLS,
    to_pascal_case,
    to_type_name,
    to_label,
    to_singular,
    col_to_ts_type,
    col_to_field_def_type,
    col_to_field_options,
    entity_icon,
    entity_emoji,
    pluralise,
)  # noqa: F401

logger = logging.getLogger(__name__)

from aether_os.phases.p05_frontend.code_writer_parts.part01 import (  # noqa: F401
    generate_package_json,
    _generate_eslint_config,
    _generate_vite_config,
    _generate_tsconfig,
    _generate_tailwind_config,
    _generate_postcss_config,
    _generate_index_html,
)
from aether_os.phases.p05_frontend.code_writer_parts.part02 import (  # noqa: F401
    _generate_nginx_conf,
    _generate_dockerfile,
    _generate_env_example,
    _generate_headers_file,
    THEME_CSS,
    SPEED_MS,
    TRANSITION_CSS,
    SKELETON_CSS,
    _generate_index_css,
    _generate_main_tsx,
    _generate_auth_ts,
    _col_to_ts_type_full,
    _generate_types,
    _generate_api,
)
from aether_os.phases.p05_frontend.code_writer_parts.part03 import (  # noqa: F401
    _generate_app,
    _generate_dual_app,
    _generate_admin_layout,
    _generate_customer_layout,
)
from aether_os.phases.p05_frontend.code_writer_parts.part04 import (  # noqa: F401
    _generate_customer_home,
    _generate_layout,
)
from aether_os.phases.p05_frontend.code_writer_parts.part05 import (  # noqa: F401
    _generate_data_table,
    _generate_crud_modal,
    _generate_toaster,
    _generate_vitest_config,
    _generate_test_setup,
    _generate_login_test,
    _generate_dashboard_test,
    _generate_error_boundary,
)
from aether_os.phases.p05_frontend.code_writer_parts.part06 import (  # noqa: F401
    _generate_not_found_page,
    _generate_pagination,
    _generate_skeleton,
    _generate_role_guard,
    _generate_frontend_readme,
)
from aether_os.phases.p05_frontend.code_writer_parts.part07 import (  # noqa: F401
    _generate_login_page,
    _generate_dashboard,
)
from aether_os.phases.p05_frontend.code_writer_parts.part08 import (  # noqa: F401
    _generate_storefront_home,
    _generate_use_sse_hook,
    _generate_use_websocket_hook,
)
from aether_os.phases.p05_frontend.code_writer_parts.part09 import (  # noqa: F401
    _generate_entity_page,
    _generate_product_grid_page,
    _is_product_entity,
)
from aether_os.phases.p05_frontend.code_writer_parts.part10 import (  # noqa: F401
    _generate_docker_compose,
    _generate_lib_utils,
    _generate_ui_button,
    _generate_ui_input,
    _generate_ui_card,
    _generate_ui_badge,
    _generate_ui_skeleton,
    _generate_ui_modal,
)
from aether_os.phases.p05_frontend.code_writer_parts.part11 import (  # noqa: F401
    _generate_ui_select,
    _generate_ui_toast,
    _generate_ui_tooltip,
    _generate_ui_table,
)
from aether_os.phases.p05_frontend.code_writer_parts.part12 import (  # noqa: F401
    _generate_domain_dashboard,
    _generate_mobile_first_layout,
    _generate_page_with_motion,
)
from aether_os.phases.p05_frontend.code_writer_parts.part13 import (  # noqa: F401
    _generate_kanban_component,
    _generate_calendar_component,
)
from aether_os.phases.p05_frontend.code_writer_parts.part14 import (  # noqa: F401
    _generate_command_palette,
)

# Public aliases for functions that task_agent.py imports by name.
# These were accidentally made private during a refactor; restoring public names here
# keeps task_agent.py's import list intact without renaming 28 internal call sites.
generate_eslint_config = _generate_eslint_config
generate_vite_config = _generate_vite_config
generate_tsconfig = _generate_tsconfig
generate_tailwind_config = _generate_tailwind_config
generate_postcss_config = _generate_postcss_config
generate_index_html = _generate_index_html
generate_nginx_conf = _generate_nginx_conf
generate_dockerfile = _generate_dockerfile
generate_env_example = _generate_env_example
generate_headers_file = _generate_headers_file
generate_index_css = _generate_index_css
generate_main_tsx = _generate_main_tsx
generate_auth_ts = _generate_auth_ts
generate_types = _generate_types
generate_api = _generate_api
generate_app = _generate_app
generate_admin_layout = _generate_admin_layout
generate_customer_layout = _generate_customer_layout
generate_customer_home = _generate_customer_home
generate_layout = _generate_layout
generate_data_table = _generate_data_table
generate_crud_modal = _generate_crud_modal
generate_toaster = _generate_toaster
generate_vitest_config = _generate_vitest_config
generate_test_setup = _generate_test_setup
generate_login_test = _generate_login_test
generate_dashboard_test = _generate_dashboard_test
generate_error_boundary = _generate_error_boundary
generate_not_found_page = _generate_not_found_page
generate_frontend_readme = _generate_frontend_readme
generate_login_page = _generate_login_page
generate_dashboard = _generate_dashboard
generate_storefront_home = _generate_storefront_home
generate_entity_page = _generate_entity_page
generate_product_grid_page = _generate_product_grid_page
generate_docker_compose = _generate_docker_compose
generate_use_sse_hook = _generate_use_sse_hook
is_product_entity = _is_product_entity

# New premium UI generators
generate_lib_utils = _generate_lib_utils
generate_ui_button = _generate_ui_button
generate_ui_input = _generate_ui_input
generate_ui_card = _generate_ui_card
generate_ui_badge = _generate_ui_badge
generate_ui_skeleton = _generate_ui_skeleton
generate_ui_modal = _generate_ui_modal
generate_ui_select = _generate_ui_select
generate_ui_toast = _generate_ui_toast
generate_ui_tooltip = _generate_ui_tooltip
generate_ui_table = _generate_ui_table
generate_domain_dashboard = _generate_domain_dashboard
generate_mobile_first_layout = _generate_mobile_first_layout
generate_page_with_motion = _generate_page_with_motion
generate_use_websocket_hook = _generate_use_websocket_hook

# New interactive view generators (Items 4-6)
generate_kanban_component = _generate_kanban_component
generate_calendar_component = _generate_calendar_component
generate_command_palette = _generate_command_palette

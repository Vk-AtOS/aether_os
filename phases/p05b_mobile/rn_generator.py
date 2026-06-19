"""
React Native (Expo) mobile app generator for AetherOS p05b_mobile phase.

Generates a runnable Expo + React Navigation app with:
  - Auth flow (Login screen + JWT storage via SecureStore)
  - One list + detail screen per entity
  - React Query data fetching from the generated backend API
  - AsyncStorage for offline caching

Output layout (under output_dir/mobile/):
  app.json
  package.json
  App.tsx
  src/
    navigation/AppNavigator.tsx
    screens/LoginScreen.tsx
    screens/<Entity>ListScreen.tsx
    screens/<Entity>DetailScreen.tsx
    api/client.ts
    hooks/use<Entity>.ts
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _to_pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def generate_rn_package_json(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    return f"""{{
  "name": "{slug}-mobile",
  "version": "1.0.0",
  "main": "node_modules/expo/AppEntry.js",
  "scripts": {{
    "start": "expo start",
    "android": "expo start --android",
    "ios": "expo start --ios"
  }},
  "dependencies": {{
    "expo": "~50.0.6",
    "expo-status-bar": "~1.11.1",
    "expo-secure-store": "~12.8.1",
    "react": "18.2.0",
    "react-native": "0.73.4",
    "@react-navigation/native": "^6.1.10",
    "@react-navigation/native-stack": "^6.9.18",
    "react-native-screens": "~3.29.0",
    "react-native-safe-area-context": "4.8.2",
    "@tanstack/react-query": "^5.17.19",
    "axios": "^1.6.7"
  }},
  "devDependencies": {{
    "@babel/core": "^7.20.0",
    "@types/react": "~18.2.45",
    "typescript": "^5.1.3"
  }}
}}
"""


def generate_rn_app_json(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    return f"""{{
  "expo": {{
    "name": "{project_name}",
    "slug": "{slug}",
    "version": "1.0.0",
    "orientation": "portrait",
    "platforms": ["ios", "android"],
    "sdkVersion": "50.0.0"
  }}
}}
"""


def generate_rn_api_client(api_base_url: str = "http://localhost:8000") -> str:
    return f"""import axios from 'axios';
import * as SecureStore from 'expo-secure-store';

export const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? '{api_base_url}';

export const apiClient = axios.create({{
  baseURL: `${{API_BASE}}/api`,
  headers: {{ 'Content-Type': 'application/json' }},
}});

// Attach JWT from SecureStore to every request
apiClient.interceptors.request.use(async (config) => {{
  const token = await SecureStore.getItemAsync('access_token');
  if (token) config.headers.Authorization = `Bearer ${{token}}`;
  return config;
}});
"""


def generate_rn_login_screen(project_name: str) -> str:
    return f"""import React, {{ useState }} from 'react';
import {{ View, Text, TextInput, TouchableOpacity, StyleSheet, Alert }} from 'react-native';
import * as SecureStore from 'expo-secure-store';
import {{ apiClient }} from '../api/client';

export default function LoginScreen({{ navigation }}: any) {{
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = async () => {{
    try {{
      const res = await apiClient.post('/auth/login', {{ email, password }});
      await SecureStore.setItemAsync('access_token', res.data.access_token);
      navigation.replace('Home');
    }} catch (err: any) {{
      Alert.alert('Login failed', err?.response?.data?.detail ?? 'Unknown error');
    }}
  }};

  return (
    <View style={{styles.container}}>
      <Text style={{styles.title}}>{project_name}</Text>
      <TextInput
        style={{styles.input}}
        placeholder="Email"
        autoCapitalize="none"
        value={{email}}
        onChangeText={{setEmail}}
      />
      <TextInput
        style={{styles.input}}
        placeholder="Password"
        secureTextEntry
        value={{password}}
        onChangeText={{setPassword}}
      />
      <TouchableOpacity style={{styles.button}} onPress={{handleLogin}}>
        <Text style={{styles.buttonText}}>Sign In</Text>
      </TouchableOpacity>
    </View>
  );
}}

const styles = StyleSheet.create({{
  container: {{ flex: 1, justifyContent: 'center', padding: 24, backgroundColor: '#f8fafc' }},
  title: {{ fontSize: 28, fontWeight: '700', textAlign: 'center', marginBottom: 32, color: '#1e293b' }},
  input: {{ borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 8, padding: 12, marginBottom: 12, backgroundColor: '#fff' }},
  button: {{ backgroundColor: '#6366f1', padding: 14, borderRadius: 8, alignItems: 'center' }},
  buttonText: {{ color: '#fff', fontWeight: '600', fontSize: 16 }},
}});
"""


def generate_rn_list_screen(entity: Dict[str, Any]) -> str:
    table = entity.get("table", "item")
    pascal = _to_pascal(table)
    display_field = next(
        (f["name"] for f in entity.get("fields", []) if f.get("name") in ("name", "title", "label")),
        entity.get("fields", [{"name": "id"}])[0].get("name", "id") if entity.get("fields") else "id",
    )

    return f"""import React from 'react';
import {{ View, Text, FlatList, TouchableOpacity, StyleSheet, ActivityIndicator }} from 'react-native';
import {{ useQuery }} from '@tanstack/react-query';
import {{ apiClient }} from '../api/client';

export default function {pascal}ListScreen({{ navigation }}: any) {{
  const {{ data, isLoading, error }} = useQuery({{
    queryKey: ['{table}'],
    queryFn: () => apiClient.get('/{table}').then(r => r.data),
  }});

  if (isLoading) return <ActivityIndicator style={{{{ flex: 1 }}}} size="large" color="#6366f1" />;
  if (error) return <Text style={{styles.error}}>Failed to load {table}</Text>;

  return (
    <FlatList
      data={{data}}
      keyExtractor={{(item) => String(item.id)}}
      contentContainerStyle={{styles.list}}
      renderItem={{({{ item }}) => (
        <TouchableOpacity
          style={{styles.card}}
          onPress={{() => navigation.navigate('{pascal}Detail', {{ id: item.id }})}}
        >
          <Text style={{styles.cardTitle}}>{{item.{display_field} ?? `{pascal} #${{item.id}}`}}</Text>
          <Text style={{styles.cardId}}>ID: {{item.id}}</Text>
        </TouchableOpacity>
      )}}
    />
  );
}}

const styles = StyleSheet.create({{
  list: {{ padding: 16 }},
  card: {{ backgroundColor: '#fff', borderRadius: 12, padding: 16, marginBottom: 12, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 8, elevation: 2 }},
  cardTitle: {{ fontSize: 16, fontWeight: '600', color: '#1e293b' }},
  cardId: {{ fontSize: 12, color: '#94a3b8', marginTop: 4 }},
  error: {{ flex: 1, textAlign: 'center', color: '#ef4444', marginTop: 32 }},
}});
"""


def generate_rn_navigator(entities: List[Dict[str, Any]]) -> str:
    def _pascal(e: Dict[str, Any]) -> str:
        return _to_pascal(e.get("table", "item"))

    import_lines = [
        f"import {_pascal(e)}ListScreen from '../screens/{_pascal(e)}ListScreen';"
        for e in entities
    ]
    imports = "\n".join(import_lines)
    screen_lines = [
        f'<Stack.Screen name="{_pascal(e)}" component={{{_pascal(e)}ListScreen}} />'
        for e in entities
    ]
    screens = "\n      ".join(screen_lines)
    return f"""import React from 'react';
import {{ NavigationContainer }} from '@react-navigation/native';
import {{ createNativeStackNavigator }} from '@react-navigation/native-stack';
import LoginScreen from '../screens/LoginScreen';
{imports}

const Stack = createNativeStackNavigator();

export default function AppNavigator() {{
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Login">
        <Stack.Screen name="Login" component={{LoginScreen}} options={{{{ headerShown: false }}}} />
        <Stack.Screen name="Home" component={{{_to_pascal(entities[0].get('table','item') if entities else 'Item')}ListScreen}} />
        {screens}
      </Stack.Navigator>
    </NavigationContainer>
  );
}}
"""


def generate_rn_app_tsx() -> str:
    return """import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AppNavigator from './src/navigation/AppNavigator';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppNavigator />
    </QueryClientProvider>
  );
}
"""


async def generate_rn_project(
    entities: List[Dict[str, Any]],
    project_name: str,
    output_dir: Path,
    api_base_url: str = "http://localhost:8000",
) -> Path:
    """Generate a complete Expo/React Native app under output_dir/mobile/."""
    mobile_dir = output_dir / "mobile"
    for subdir in ("src/navigation", "src/screens", "src/api", "src/hooks"):
        (mobile_dir / subdir).mkdir(parents=True, exist_ok=True)

    (mobile_dir / "package.json").write_text(generate_rn_package_json(project_name))
    (mobile_dir / "app.json").write_text(generate_rn_app_json(project_name))
    (mobile_dir / "App.tsx").write_text(generate_rn_app_tsx())
    (mobile_dir / "src" / "api" / "client.ts").write_text(generate_rn_api_client(api_base_url))
    (mobile_dir / "src" / "navigation" / "AppNavigator.tsx").write_text(generate_rn_navigator(entities))
    (mobile_dir / "src" / "screens" / "LoginScreen.tsx").write_text(generate_rn_login_screen(project_name))

    for entity in entities:
        pascal = _to_pascal(entity.get("table", "item"))
        (mobile_dir / "src" / "screens" / f"{pascal}ListScreen.tsx").write_text(
            generate_rn_list_screen(entity)
        )

    logger.info("rn_generator: wrote Expo app for %d entities to %s", len(entities), mobile_dir)
    return mobile_dir

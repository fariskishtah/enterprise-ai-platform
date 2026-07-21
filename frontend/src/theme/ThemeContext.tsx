import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

export type ThemePreference = "dark" | "light" | "system";

interface ThemeContextValue {
  readonly preference: ThemePreference;
  readonly resolvedTheme: "dark" | "light";
  readonly setPreference: (preference: ThemePreference) => void;
}

const STORAGE_KEY = "fk-theme-preference";
const ThemeContext = createContext<ThemeContextValue | null>(null);

function storedPreference(): ThemePreference {
  const value = localStorage.getItem(STORAGE_KEY);
  return value === "dark" || value === "light" || value === "system" ? value : "system";
}

function systemTheme(): "dark" | "light" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({
  children,
}: {
  readonly children: ReactNode;
}): ReactElement {
  const [preference, setPreferenceState] = useState<ThemePreference>(storedPreference);
  const [system, setSystem] = useState<"dark" | "light">(systemTheme);
  const resolvedTheme = preference === "system" ? system : preference;

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const update = (): void => setSystem(query.matches ? "dark" : "light");
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.style.colorScheme = resolvedTheme;
  }, [resolvedTheme]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolvedTheme,
      setPreference: (next) => {
        localStorage.setItem(STORAGE_KEY, next);
        setPreferenceState(next);
      },
    }),
    [preference, resolvedTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === null) throw new Error("useTheme must be used within ThemeProvider.");
  return context;
}

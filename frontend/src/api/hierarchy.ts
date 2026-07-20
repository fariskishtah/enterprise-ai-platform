import { apiRequest } from "./client";

export interface PaginatedResponse<T> {
  readonly items: readonly T[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

interface ResourceTimestamps {
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Company extends ResourceTimestamps {
  readonly description: string | null;
  readonly id: string;
  readonly name: string;
}

export interface Factory extends ResourceTimestamps {
  readonly company_id: string;
  readonly description: string | null;
  readonly id: string;
  readonly location: string | null;
  readonly name: string;
}

export interface Machine extends ResourceTimestamps {
  readonly factory_id: string;
  readonly id: string;
  readonly manufacturer: string | null;
  readonly model: string | null;
  readonly name: string;
  readonly serial_number: string | null;
}

export interface Sensor extends ResourceTimestamps {
  readonly description: string | null;
  readonly id: string;
  readonly machine_id: string;
  readonly max_value: number;
  readonly min_value: number;
  readonly name: string;
  readonly sampling_rate: number;
  readonly sensor_type: string | null;
  readonly unit: string | null;
}

export interface FactoryInput {
  readonly company_id: string;
  readonly description: string | null;
  readonly location: string | null;
  readonly name: string;
}

export interface MachineInput {
  readonly factory_id: string;
  readonly manufacturer: string | null;
  readonly model: string | null;
  readonly name: string;
  readonly serial_number: string | null;
}

export interface SensorInput {
  readonly description: string | null;
  readonly machine_id: string;
  readonly max_value: number;
  readonly min_value: number;
  readonly name: string;
  readonly sampling_rate: number;
  readonly sensor_type: string | null;
  readonly unit: string | null;
}

interface ListOptions {
  readonly limit?: number;
  readonly offset?: number;
  readonly signal?: AbortSignal;
}

function queryString(values: Record<string, number | string | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) {
      query.set(key, String(value));
    }
  });
  const encoded = query.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

export function listCompanies(
  options: ListOptions = {},
): Promise<PaginatedResponse<Company>> {
  return apiRequest(
    `/companies${queryString({
      limit: options.limit ?? 100,
      offset: options.offset ?? 0,
      sort_by: "name",
      sort_order: "asc",
    })}`,
    { signal: options.signal },
  );
}

export async function listAllCompanies(
  signal?: AbortSignal,
): Promise<readonly Company[]> {
  const first = await listCompanies({ limit: 100, signal });
  const companies = [...first.items];
  while (companies.length < first.total) {
    const page = await listCompanies({ limit: 100, offset: companies.length, signal });
    companies.push(...page.items);
  }
  return companies;
}

export function getCompany(companyId: string, signal?: AbortSignal): Promise<Company> {
  return apiRequest(`/companies/${companyId}`, { signal });
}

export function listFactories(
  options: ListOptions = {},
): Promise<PaginatedResponse<Factory>> {
  return apiRequest(
    `/factories${queryString({
      limit: options.limit ?? 20,
      offset: options.offset ?? 0,
      sort_by: "name",
      sort_order: "asc",
    })}`,
    { signal: options.signal },
  );
}

export function getFactory(factoryId: string, signal?: AbortSignal): Promise<Factory> {
  return apiRequest(`/factories/${factoryId}`, { signal });
}

export function createFactory(payload: FactoryInput): Promise<Factory> {
  return apiRequest("/factories", { body: JSON.stringify(payload), method: "POST" });
}

export function updateFactory(
  factoryId: string,
  payload: FactoryInput,
): Promise<Factory> {
  return apiRequest(`/factories/${factoryId}`, {
    body: JSON.stringify(payload),
    method: "PATCH",
  });
}

export function deleteFactory(factoryId: string): Promise<void> {
  return apiRequest(`/factories/${factoryId}`, { method: "DELETE" });
}

export function listMachines(
  factoryId: string,
  options: ListOptions = {},
): Promise<PaginatedResponse<Machine>> {
  return apiRequest(
    `/machines${queryString({
      factory_id: factoryId,
      limit: options.limit ?? 100,
      offset: options.offset ?? 0,
      sort_by: "name",
      sort_order: "asc",
    })}`,
    { signal: options.signal },
  );
}

export function getMachine(machineId: string, signal?: AbortSignal): Promise<Machine> {
  return apiRequest(`/machines/${machineId}`, { signal });
}

export function createMachine(payload: MachineInput): Promise<Machine> {
  return apiRequest("/machines", { body: JSON.stringify(payload), method: "POST" });
}

export function updateMachine(
  machineId: string,
  payload: MachineInput,
): Promise<Machine> {
  return apiRequest(`/machines/${machineId}`, {
    body: JSON.stringify(payload),
    method: "PATCH",
  });
}

export function deleteMachine(machineId: string): Promise<void> {
  return apiRequest(`/machines/${machineId}`, { method: "DELETE" });
}

export function listSensors(
  machineId: string,
  options: ListOptions = {},
): Promise<PaginatedResponse<Sensor>> {
  return apiRequest(
    `/machines/${machineId}/sensors${queryString({
      limit: options.limit ?? 100,
      offset: options.offset ?? 0,
      sort_by: "name",
      sort_order: "asc",
    })}`,
    { signal: options.signal },
  );
}

export function getSensor(sensorId: string, signal?: AbortSignal): Promise<Sensor> {
  return apiRequest(`/sensors/${sensorId}`, { signal });
}

export function createSensor(payload: SensorInput): Promise<Sensor> {
  return apiRequest("/sensors", { body: JSON.stringify(payload), method: "POST" });
}

export function updateSensor(sensorId: string, payload: SensorInput): Promise<Sensor> {
  return apiRequest(`/sensors/${sensorId}`, {
    body: JSON.stringify(payload),
    method: "PATCH",
  });
}

export function deleteSensor(sensorId: string): Promise<void> {
  return apiRequest(`/sensors/${sensorId}`, { method: "DELETE" });
}

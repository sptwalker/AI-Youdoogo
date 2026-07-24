export interface DatedResult<T> {
  date: string
  value: T
}

export function valueForDate<T>(result: DatedResult<T> | null, date: string): T | null {
  return result?.date === date ? result.value : null
}

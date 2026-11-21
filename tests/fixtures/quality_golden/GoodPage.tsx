import { useEffect, useState } from 'react'

interface Row { id: number; name: string }

export function GoodPage() {
  const [rows, setRows] = useState<Row[]>([])
  useEffect(() => {
    fetch('/api/items')
      .then((r) => r.json())
      .then(setRows)
      .catch(() => setRows([]))
  }, [])
  return (
    <ul>
      {rows.map((r) => (
        <li key={r.id}>{r.name}</li>
      ))}
      <li><img src="/x.png" alt="logo" /></li>
      <li><input aria-label="search" /></li>
    </ul>
  )
}

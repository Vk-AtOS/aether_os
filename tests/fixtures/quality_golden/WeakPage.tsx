// @ts-nocheck
export function WeakPage({ data }: { data: any }) {
  // TODO finish
  console.log(data)
  fetch('/api/x')
  try { run() } catch (e) {}
  return (
    <div>
      {data.map((d: any, index: number) => <img key={index} src={d.src} />)}
      <input />
      <button onClick={() => go()}><span /></button>
    </div>
  )
}

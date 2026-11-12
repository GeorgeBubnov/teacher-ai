import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API = 'http://localhost:8000'

function App() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function parse() {
    if (!file) return
    setBusy(true); setError('')
    const body = new FormData(); body.append('file', file)
    try {
      const response = await fetch(`${API}/api/parse`, { method: 'POST', body })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Не удалось обработать файл')
      setResult(data)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  function updateRow(index, field, value) {
    setResult(current => ({ ...current, rows: current.rows.map((row, i) => i === index ? { ...row, [field]: field === 'hours' ? (value ? Number(value) : null) : value } : row) }))
  }

  async function save() {
    await fetch(`${API}/api/results/${result.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: result.rows, warnings: result.warnings }) })
  }

  return <main>
    <header><div className="eyebrow">ПЛАН-КОНТРОЛЬ</div><h1>Извлеките структуру учебного плана</h1><p>Загрузите учебно-календарный план в формате .doc, .docx или .pdf. Система выделит темы, часы и компетенции, а результат можно проверить и скачать в JSON.</p></header>
    <section className="upload-card">
      <label className="drop"><input type="file" accept=".doc,.docx,.pdf" onChange={e => setFile(e.target.files[0])} /><strong>{file ? file.name : 'Выберите файл .doc, .docx или .pdf'}</strong><span>{file ? 'Файл готов к обработке' : 'Нажмите здесь, чтобы загрузить учебно-календарный план'}</span></label>
      <button disabled={!file || busy} onClick={parse}>{busy ? 'Обрабатываем...' : 'Распарсить документ'}</button>
      {error && <div className="error">{error}</div>}
    </section>
    {result && <section className="result"><div className="result-head"><div><div className="eyebrow">РЕЗУЛЬТАТ</div><h2>{result.filename}</h2><span>{result.rows.length} строк найдено</span></div><div className="actions"><button className="quiet" onClick={save}>Сохранить правки</button><a className="button" href={`${API}/api/results/${result.id}/download`}>Скачать JSON</a></div></div>
      {(!!result.warnings.length || result.diagnostics?.message) && <div className="warnings"><b>{result.diagnostics?.message || 'Проверить вручную'}</b>{result.warnings.map((warning, i) => <div key={i}>{warning}</div>)}</div>}
      <div className="table-wrap"><table><thead><tr><th>#</th><th>Тема урока</th><th>Количество часов</th><th>УДД / компетенции</th></tr></thead><tbody>{result.rows.map((row, i) => <tr key={i}><td>{i + 1}</td><td><input value={row.topic} onChange={e => updateRow(i, 'topic', e.target.value)} /></td><td><input type="number" min="0" value={row.hours ?? ''} onChange={e => updateRow(i, 'hours', e.target.value)} /></td><td><textarea value={row.udd} onChange={e => updateRow(i, 'udd', e.target.value)} /></td></tr>)}</tbody></table></div>
    </section>}
  </main>
}

createRoot(document.getElementById('root')).render(<App />)

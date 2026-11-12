import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

const API = 'http://localhost:8100'

function App() {
  const [file, setFile] = useState(null)
  const [topic, setTopic] = useState('')
  const [pages, setPages] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault(); if (!file) return
    setBusy(true); setError('')
    const body = new FormData(); body.append('file', file); body.append('topic', topic); body.append('pages', pages)
    try { const response = await fetch(`${API}/api/material`, { method: 'POST', body }); const data = await response.json(); if (!response.ok) throw new Error(data.detail); setResult(data) }
    catch (err) { setError(err.message || 'Не удалось подготовить материал') } finally { setBusy(false) }
  }

  return <main><header><div className="tag">УЧЕБНЫЙ МАТЕРИАЛ</div><h1>Одна тема.<br/><em>Пятнадцать минут.</em></h1><p>Загрузите PDF учебника, укажите тему, и получите готовое объяснение сплошным текстом для проведения урока.</p></header><form onSubmit={submit} className="panel"><label className="file"><input type="file" accept=".pdf" onChange={e => setFile(e.target.files[0])}/><b>{file ? file.name : 'Выбрать PDF учебника'}</b><span>{file ? 'Файл выбран' : 'Поддерживается формат PDF'}</span></label><div className="fields"><label>Тема урока<input value={topic} onChange={e => setTopic(e.target.value)} placeholder="Например: Признаки равенства треугольников"/></label><label>Страницы, необязательно<input value={pages} onChange={e => setPages(e.target.value)} placeholder="Например: 42–45"/></label></div><button disabled={!file || busy}>{busy ? 'Готовим материал...' : 'Подготовить текст'}</button>{error && <div className="error">{error}</div>}</form>{result && <section className="output"><div className="output-head"><div><div className="tag">ГОТОВЫЙ ТЕКСТ</div><h2>{result.topic || 'Материал урока'}</h2></div><button className="copy" onClick={() => navigator.clipboard.writeText(result.text)}>Копировать текст</button></div><article>{result.text}</article></section>}</main>
}
createRoot(document.getElementById('root')).render(<App />)

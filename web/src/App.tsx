import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { DiscordLayout } from './components/DiscordLayout'
import { TradePage } from './pages/TradePage'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DiscordLayout />} />
        <Route path="/trade" element={<TradePage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App

/** Mask coordinates and exported pixels always match the original image. */
import { useEffect, useRef, useState } from 'react'

export interface MaskCanvasApi {
  exportMask: () => string | null
  hasMask: () => boolean
  clear: () => void
}

export function MaskCanvas({ baseImage, brushSize, erase, apiRef, onMaskChange }: {
  baseImage: string
  brushSize: number
  erase?: boolean
  apiRef: React.MutableRefObject<MaskCanvasApi | null>
  onMaskChange: (mask: string) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const last = useRef<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState({ width: 1, height: 1 })
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let alive = true
    setReady(false)
    onMaskChange('')
    const image = new Image()
    image.onload = () => {
      if (!alive || !canvasRef.current) return
      canvasRef.current.width = image.naturalWidth
      canvasRef.current.height = image.naturalHeight
      setSize({ width: image.naturalWidth, height: image.naturalHeight })
      setReady(true)
    }
    image.src = baseImage
    return () => { alive = false }
  }, [baseImage, onMaskChange])

  const hasMask = () => {
    const canvas = canvasRef.current
    const data = canvas?.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data
    if (data) for (let i = 3; i < data.length; i += 4) if (data[i] > 0) return true
    return false
  }
  const exportMask = () => {
    const canvas = canvasRef.current
    if (!canvas || !hasMask()) { onMaskChange(''); return null }
    const output = document.createElement('canvas')
    output.width = canvas.width
    output.height = canvas.height
    const ctx = output.getContext('2d')
    if (!ctx) return null
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, output.width, output.height)
    ctx.drawImage(canvas, 0, 0)
    const mask = output.toDataURL('image/png')
    onMaskChange(mask)
    return mask
  }
  useEffect(() => {
    apiRef.current = { exportMask, hasMask, clear: () => {
      const canvas = canvasRef.current
      if (canvas) canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
      onMaskChange('')
    } }
    return () => { apiRef.current = null }
  })

  const stroke = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = event.currentTarget
    const ctx = canvas.getContext('2d')
    if (!ctx || !ready) return
    const rect = canvas.getBoundingClientRect()
    const ratio = canvas.width / rect.width
    const x = (event.clientX - rect.left) * ratio
    const y = (event.clientY - rect.top) * canvas.height / rect.height
    ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over'
    ctx.strokeStyle = '#fff'
    ctx.fillStyle = '#fff'
    ctx.lineWidth = brushSize * ratio
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.beginPath()
    ctx.moveTo(last.current?.x ?? x, last.current?.y ?? y)
    ctx.lineTo(x, y)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(x, y, brushSize * ratio / 2, 0, 2 * Math.PI)
    ctx.fill()
    last.current = { x, y }
  }
  const finish = () => {
    if (!drawing.current) return
    drawing.current = false
    last.current = null
    exportMask()
  }

  return <div className="if-mask-canvas relative overflow-hidden rounded-xl border border-(--ui-stroke-secondary)" style={{ aspectRatio: `${size.width}/${size.height}`, maxWidth: `calc(60vh * ${size.width} / ${size.height})` }}>
    <img src={baseImage} alt="" className="absolute inset-0 h-full w-full object-contain" />
    <canvas ref={canvasRef} className="absolute inset-0 h-full w-full cursor-crosshair opacity-60 mix-blend-screen" style={{ touchAction: 'none' }}
      onPointerDown={(event) => { if (!ready) return; event.currentTarget.setPointerCapture(event.pointerId); drawing.current = true; last.current = null; stroke(event) }}
      onPointerMove={(event) => { if (drawing.current) stroke(event) }} onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish} />
  </div>
}

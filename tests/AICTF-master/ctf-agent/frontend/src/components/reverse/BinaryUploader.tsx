import { useCallback, useState, useRef } from 'react'
import { Upload, FileUp } from 'lucide-react'

interface BinaryUploaderProps {
  onUpload: (file: File) => Promise<void>
  uploading: boolean
}

export default function BinaryUploader({ onUpload, uploading }: BinaryUploaderProps) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      const file = e.dataTransfer.files[0]
      if (file) onUpload(file)
    },
    [onUpload]
  )

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) onUpload(file)
      if (inputRef.current) inputRef.current.value = ''
    },
    [onUpload]
  )

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`
        relative flex flex-col items-center justify-center gap-2 p-6 rounded-xl border-2 border-dashed cursor-pointer
        transition-all duration-200
        ${dragOver
          ? 'border-purple-500 bg-purple-50'
          : 'border-gray-200 bg-white hover:border-purple-300 hover:bg-gray-50'
        }
        ${uploading ? 'pointer-events-none opacity-60' : ''}
      `}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={handleFileSelect}
        accept=".elf,.exe,.bin,.so,.dll,.o,.out,.pyc,.class,.apk,.dex,*"
      />
      {uploading ? (
        <>
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-purple-500 border-t-transparent" />
          <span className="text-sm text-gray-500">上传中...</span>
        </>
      ) : (
        <>
          <div className="p-3 rounded-full bg-purple-50">
            {dragOver ? (
              <FileUp className="w-6 h-6 text-purple-500" />
            ) : (
              <Upload className="w-6 h-6 text-purple-400" />
            )}
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-700">拖拽二进制文件到此处</p>
            <p className="text-xs text-gray-500 mt-1">支持 ELF / PE / Mach-O / .pyc / 任意格式</p>
          </div>
        </>
      )}
    </div>
  )
}

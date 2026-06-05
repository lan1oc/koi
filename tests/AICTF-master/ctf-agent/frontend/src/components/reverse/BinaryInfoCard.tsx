import { Shield, ShieldAlert, ShieldCheck, ShieldX, FileCode, Cpu, HardDrive, Package } from 'lucide-react'
import type { ReverseBinary } from '../../types'

interface BinaryInfoCardProps {
  binary: ReverseBinary
  analyzing: boolean
  onAnalyze: () => void
}

function SecurityBadge({ label, value }: { label: string; value?: string }) {
  const isEnabled = value === 'enabled' || value === 'yes' || value === 'Full'
  const isPartial = value === 'Partial'
  const isDisabled = value === 'disabled' || value === 'no' || value === 'No'

  let color = 'text-gray-500 bg-gray-100'
  let Icon = Shield
  if (isEnabled) {
    color = 'text-green-600 bg-green-50'
    Icon = ShieldCheck
  } else if (isPartial) {
    color = 'text-yellow-600 bg-yellow-50'
    Icon = ShieldAlert
  } else if (isDisabled) {
    color = 'text-red-600 bg-red-50'
    Icon = ShieldX
  }

  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg ${color}`}>
      <Icon className="w-3.5 h-3.5" />
      <span className="text-xs font-medium">{label}</span>
      <span className="text-xs opacity-70">{value || 'N/A'}</span>
    </div>
  )
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function BinaryInfoCard({ binary, analyzing, onAnalyze }: BinaryInfoCardProps) {
  return (
    <div className="space-y-4">
      {/* File metadata */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2 p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <FileCode className="w-4 h-4 text-purple-500 shrink-0" />
          <div className="min-w-0">
            <p className="text-xs text-gray-500">文件类型</p>
            <p className="text-sm text-gray-800 truncate" title={binary.file_type}>
              {binary.file_type || '未检测'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <Cpu className="w-4 h-4 text-blue-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">架构</p>
            <p className="text-sm text-gray-800">{binary.arch || '未检测'}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <HardDrive className="w-4 h-4 text-gray-400 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">大小</p>
            <p className="text-sm text-gray-800">{formatFileSize(binary.file_size)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <Package className="w-4 h-4 text-orange-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">壳检测</p>
            <p className={`text-sm font-medium ${binary.packer_info?.packed ? 'text-red-600' : 'text-green-600'}`}>
              {binary.packer_info?.packed ? binary.packer_info.type : '无壳'}
            </p>
          </div>
        </div>
      </div>

      {/* Packer info */}
      {binary.packer_info?.packed && (
        <div className="p-3 rounded-xl bg-red-50 border border-red-200">
          <div className="flex items-center gap-2 mb-1">
            <Package className="w-4 h-4 text-red-500" />
            <span className="text-sm font-medium text-red-700">
              检测到加壳: {binary.packer_info.type}
            </span>
            <span className="text-xs text-red-500">
              置信度: {(binary.packer_info.confidence * 100).toFixed(0)}%
            </span>
          </div>
          <p className="text-xs text-red-600 ml-6">{binary.packer_info.details}</p>
          {binary.packer_info.suggestion && (
            <p className="text-xs text-amber-700 ml-6 mt-1">
              💡 {binary.packer_info.suggestion}
            </p>
          )}
        </div>
      )}

      {/* Checksec */}
      {binary.checksec ? (
        <div>
          <h4 className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wider">安全特性</h4>
          <div className="flex flex-wrap gap-2">
            <SecurityBadge label="NX" value={binary.checksec.nx} />
            <SecurityBadge label="PIE" value={binary.checksec.pie} />
            <SecurityBadge label="Canary" value={binary.checksec.canary} />
            <SecurityBadge label="RELRO" value={binary.checksec.relro} />
            {binary.checksec.stripped && (
              <SecurityBadge label="Stripped" value={binary.checksec.stripped} />
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={onAnalyze}
          disabled={analyzing}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
            bg-purple-50 border border-purple-200 text-purple-600 hover:bg-purple-100
            disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
        >
          {analyzing ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-purple-500 border-t-transparent" />
              分析中...
            </>
          ) : (
            <>
              <Shield className="w-4 h-4" />
              运行完整分析
            </>
          )}
        </button>
      )}
    </div>
  )
}

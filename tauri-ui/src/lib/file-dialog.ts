export type DialogFilter = {
  name: string;
  extensions: string[];
};

export type FileOrDirectoryMode = 'file' | 'directory' | 'file-or-directory';

export type BaseDialogOptions = {
  title: string;
  defaultPath?: string;
  filters?: DialogFilter[];
};

export type OpenPathOptions = BaseDialogOptions & {
  multiple?: boolean;
  directory?: boolean;
};

export function canUseProjectFileDialog() {
  return true;
}

import type { KoiModule } from '../../lib/types';
import { ModelToolsPage } from './ModelToolsPage';
import { TestWorkbenchPage } from './TestWorkbenchPage';

export const aiTestingModule: KoiModule = {
  id: 'ai-testing',
  title: 'AI测试',
  functions: [
    {
      id: 'test-workbench',
      title: '测试工作台',
      component: TestWorkbenchPage,
    },
    {
      id: 'model-tools',
      title: '模型与工具',
      component: ModelToolsPage,
    },
  ],
};

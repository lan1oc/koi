import type { ReactElement } from 'react';

export type FunctionPage = {
  id: string;
  title: string;
  component: () => ReactElement;
};

export type KoiModule = {
  id: string;
  title: string;
  functions: FunctionPage[];
};

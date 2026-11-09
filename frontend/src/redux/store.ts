import { configureStore } from '@reduxjs/toolkit';

type AppState = Record<string, never>;

const rootReducer = (state: AppState = {}) => state;

export const store = configureStore({ reducer: rootReducer });
export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

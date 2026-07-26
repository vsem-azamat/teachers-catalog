import { createBrowserRouter } from 'react-router';
import AskPage from '@/pages/Ask';
import BecomeHelperPage from '@/pages/BecomeHelper';
import ChatsPage from '@/pages/Chats';
import HelperPage from '@/pages/Helper';
import HomePage from '@/pages/Home';
import LifePage from '@/pages/Life';
import MinePage from '@/pages/Mine';
import MyHelperPage from '@/pages/MyHelper';
import NotFoundPage from '@/pages/NotFound';
import ProfilePage from '@/pages/Profile';
import RequestPage from '@/pages/Request';
import ResultsPage from '@/pages/Results';
import Root from '@/Root';

/**
 * A browser router, not a hash router.
 *
 * The app is served from its own origin alongside the API, so real paths work
 * and survive a reload. Telegram's own back button is bound to this history in
 * `Root`.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <Root />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'ask', element: <AskPage /> },
      { path: 'results', element: <ResultsPage /> },
      { path: 'helper/:id', element: <HelperPage /> },
      { path: 'mine', element: <MinePage /> },
      { path: 'request/:id', element: <RequestPage /> },
      { path: 'chats', element: <ChatsPage /> },
      { path: 'become-helper', element: <BecomeHelperPage /> },
      { path: 'my-helper', element: <MyHelperPage /> },
      { path: 'life', element: <LifePage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]);

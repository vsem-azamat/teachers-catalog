import { Trans } from '@lingui/react/macro';
import { openTelegramLink } from '@tma.js/sdk-react';
import { ChatIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import { Empty, Head, Row, Rows, Screen, Tile, Title } from '@/components/Ui';

/**
 * There is no chat here, and there should not be.
 *
 * Conversations happen in Telegram, where both people already are and where
 * they can send a photo of the exam paper without us building an uploader.
 * This screen only points at them.
 */
export default function ChatsPage() {
  return (
    <>
      <Screen withTabs>
        <Head />
        <Title>
          <Trans>Чаты</Trans>
        </Title>
        <div style={{ height: 8 }} />
        <Rows>
          <Row
            leading={
              <Tile tone={0}>
                <ChatIcon size={19} />
              </Tile>
            }
            title={<Trans>Открыть переписку в Telegram</Trans>}
            hint={<Trans>там же, где и все остальные разговоры</Trans>}
            onClick={() => openTelegramLink('https://t.me')}
          />
        </Rows>
        <Empty
          title={<Trans>Разговоры мы не храним</Trans>}
          body={
            <Trans>
              Мы сводим людей и запоминаем, что контакт состоялся — по этому считается
              время ответа. Сама переписка остаётся в Telegram.
            </Trans>
          }
        />
      </Screen>
      <TabBar />
    </>
  );
}

import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { LanguageIcon, PersonIcon, SealIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import {
  AvatarView,
  Chips,
  ChipView,
  Head,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Sub,
  Tile,
  Title,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { activateLocale, LOCALE_NAMES, LOCALES, type Locale } from '@/i18n';
import { api } from '@/lib/api';

/**
 * Settings, and the way in to offering help.
 *
 * The languages someone speaks are not decoration here — they filter the
 * catalog. A Ukrainian first-year cannot work with a Czech-only tutor, so the
 * question is asked plainly rather than inferred.
 */
export default function ProfilePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { i18n } = useLingui();

  const { data: me, isPending } = useQuery({
    queryKey: ['me'],
    queryFn: ({ signal }) => api.getMe(signal),
  });

  const { data: languages } = useQuery({
    queryKey: ['languages'],
    queryFn: ({ signal }) => api.getLanguages(signal),
    staleTime: 60 * 60 * 1000,
  });

  const update = useMutation({
    mutationFn: api.updateMe,
    onSuccess: (next) => {
      queryClient.setQueryData(['me'], next);
      // Names of subjects and faculties come back translated, so a language
      // change invalidates everything the server rendered.
      void queryClient.invalidateQueries();
    },
  });

  const setLocale = async (locale: Locale) => {
    hapticSelection();
    await activateLocale(locale);
    document.documentElement.lang = locale;
    update.mutate({ ui_lang: locale });
  };

  const toggleLanguage = (code: string) => {
    if (!me) return;
    hapticSelection();
    const spoken = new Set(me.spoken_langs);
    if (!spoken.delete(code)) spoken.add(code);
    update.mutate({ spoken_langs: [...spoken] });
  };

  return (
    <>
      <Screen withTabs>
        <Head />
        {isPending || !me ? (
          <>
            <Title>
              <Trans>Профиль</Trans>
            </Title>
            <div style={{ height: 16 }} />
            <SkeletonRows count={4} />
          </>
        ) : (
          <>
            <div
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'center',
                marginTop: 14,
              }}
            >
              <AvatarView avatar={me.avatar} size={58} square />
              <div style={{ minWidth: 0 }}>
                <Title>{me.name}</Title>
                {me.username ? <Sub>@{me.username}</Sub> : null}
              </div>
            </div>

            <Label>
              <Trans>Язык приложения</Trans>
            </Label>
            <Chips>
              {LOCALES.map((locale) => (
                <ChipView
                  key={locale}
                  active={i18n.locale === locale}
                  onClick={() => void setLocale(locale)}
                >
                  {LOCALE_NAMES[locale]}
                </ChipView>
              ))}
            </Chips>

            <Label>
              <Trans>На каких языках тебе удобно</Trans>
            </Label>
            <Chips>
              {(languages ?? []).map((language) => (
                <ChipView
                  key={language.code}
                  active={me.spoken_langs.includes(language.code)}
                  onClick={() => toggleLanguage(language.code)}
                >
                  {language.name}
                </ChipView>
              ))}
            </Chips>
            <div style={{ marginTop: 9 }}>
              <Hint>
                <Trans>По этому мы отсеиваем тех, с кем вы друг друга не поймёте.</Trans>
              </Hint>
            </div>

            <Label>
              <Trans>Помогать другим</Trans>
            </Label>
            <Rows>
              <Row
                onClick={() => navigate('/become-helper')}
                leading={
                  <Tile tone={0}>
                    <PersonIcon size={19} />
                  </Tile>
                }
                title={
                  me.is_helper ? <Trans>Моя анкета</Trans> : <Trans>Хочу помогать</Trans>
                }
                hint={
                  me.helper_status === 'published' ? (
                    <Trans>опубликована</Trans>
                  ) : me.is_helper ? (
                    <Trans>черновик — не видна в каталоге</Trans>
                  ) : (
                    <Trans>расскажи своими словами, анкету соберём сами</Trans>
                  )
                }
              />
              <Row
                onClick={() => navigate('/life')}
                leading={
                  <Tile tone={3}>
                    <SealIcon size={19} />
                  </Tile>
                }
                title={<Trans>Жизнь в Чехии</Trans>}
                hint={<Trans>страховка, виза, банк, переводы</Trans>}
              />
              <Row
                onClick={() => navigate('/results?service=language_tutoring')}
                leading={
                  <Tile tone={2}>
                    <LanguageIcon size={19} />
                  </Tile>
                }
                title={<Trans>Чешский для вуза</Trans>}
                hint={<Trans>B1, B2, нострификация</Trans>}
              />
            </Rows>
          </>
        )}
        <div style={{ height: 20 }} />
      </Screen>
      <TabBar />
    </>
  );
}

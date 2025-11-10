import asyncio
import cli_ui
import copy
import os
import sys

from torf import Torrent

from data.config import config
from src.cleanup import cleanup, reset_terminal
from src.clients import Clients
from src.console import console
from src.dupe_checking import filter_dupes
from src.imdb import get_imdb_info_api
from src.torrentcreate import create_base_from_existing_torrent
from src.trackers.PTP import PTP
from src.trackersetup import TRACKER_SETUP, tracker_class_map, http_trackers
from src.uphelper import UploadHelper


async def process_all_trackers(meta):
    """
    Processa todos os trackers listados em meta['trackers']:
    - Valida credenciais/banimentos
    - Faz checagem de duplicatas
    - Pergunta (ou não) sobre envio conforme modo assistido/não assistido
    - Preenche meta['tracker_status'] com o resultado por tracker
    Retorna a contagem de trackers aprovados para upload.
    """
    tracker_status = {}
    successful_trackers = 0
    client = Clients(config=config)
    tracker_setup = TRACKER_SETUP(config=config)
    helper = UploadHelper()
    meta_lock = asyncio.Lock()  # noqa F841

    for tracker in meta['trackers']:
        if 'tracker_status' not in meta:
            meta['tracker_status'] = {}
        if tracker not in meta['tracker_status']:
            meta['tracker_status'][tracker] = {}

    async def process_single_tracker(tracker_name, shared_meta):
        nonlocal successful_trackers
        # Cada tarefa trabalha com uma cópia local para evitar efeitos colaterais
        local_meta = copy.deepcopy(shared_meta)
        local_tracker_status = {
            'banned': False,
            'skipped': False,
            'dupe': False,
            'upload': False,
            'other': False
        }
        disctype = local_meta.get('disctype', None)

        # Remove marcador temporário de possível dupe do nome
        if local_meta['name'].endswith('DUPE?'):
            local_meta['name'] = local_meta['name'].replace(' DUPE?', '')

        # Tracker manual: marcado como aprovado
        if tracker_name == "MANUAL":
            local_tracker_status['upload'] = True
            successful_trackers += 1

        if tracker_name in tracker_class_map:
            tracker_class = tracker_class_map[tracker_name](config=config)

            # Trackers HTTP: valida login/credenciais
            if tracker_name in http_trackers:
                login = await tracker_class.validate_credentials(meta)
                if not login:
                    local_tracker_status['skipped'] = True
                if isinstance(login, str) and login:
                    local_meta[f'{tracker_name}_secret_token'] = login
                    meta[f'{tracker_name}_secret_token'] = login

            # Pede IMDB quando necessário (THR/PTP)
            if tracker_name in {"THR", "PTP"}:
                if local_meta.get('imdb_id', 0) == 0:
                    while True:
                        if local_meta.get('unattended', False):
                            local_meta['imdb_id'] = 0
                            local_tracker_status['skipped'] = True
                            break
                        try:
                            imdb_id = cli_ui.ask_string(
                                f"Não foi possível localizar o ID do IMDB. "
                                f"Digite, por exemplo, (tt1234567) ou pressione Enter para pular o envio para {tracker_name}:"
                            )
                        except EOFError:
                            console.print("\n[red]Saindo a pedido do usuário (Ctrl+C)[/red]")
                            await cleanup()
                            reset_terminal()
                            sys.exit(1)

                        if imdb_id is None or imdb_id.strip() == "":
                            local_meta['imdb_id'] = 0
                            break

                        imdb_id = imdb_id.strip().lower()
                        if imdb_id.startswith("tt") and imdb_id[2:].isdigit():
                            local_meta['imdb_id'] = int(imdb_id[2:])
                            local_meta['imdb'] = str(imdb_id[2:].zfill(7))
                            local_meta['imdb_info'] = await get_imdb_info_api(local_meta['imdb_id'], local_meta)
                            break
                        else:
                            cli_ui.error("Formato inválido de IMDB ID. Formato esperado: tt1234567")

            # Checa grupos banidos
            result = await tracker_setup.check_banned_group(
                tracker_class.tracker, tracker_class.banned_groups, local_meta
            )
            local_tracker_status['banned'] = bool(result)

            # Respeita sinalização de pulo de upload por tracker
            if local_meta['tracker_status'][tracker_name].get('skip_upload'):
                local_tracker_status['skipped'] = True
            elif 'skipped' not in local_meta and local_tracker_status['skipped'] is None:
                local_tracker_status['skipped'] = False

            # Se não banido/ignorado, seguir com reivindicações/dupes
            if not local_tracker_status['banned'] and not local_tracker_status['skipped']:
                # Verifica se já há “claim” ativo no tracker
                claimed = await tracker_setup.get_torrent_claims(local_meta, tracker_name)
                local_tracker_status['skipped'] = bool(claimed)

                # Busca de dupes
                if tracker_name not in {"PTP"} and not local_tracker_status['skipped']:
                    dupes = await tracker_class.search_existing(local_meta, disctype)
                    if local_meta['tracker_status'][tracker_name].get('other', False):
                        local_tracker_status['other'] = True
                elif tracker_name == "PTP":
                    ptp = PTP(config=config)
                    groupID = await ptp.get_group_by_imdb(local_meta['imdb'])
                    meta['ptp_groupID'] = groupID
                    dupes = await ptp.search_existing(groupID, local_meta, disctype)

                # Aviso sobre anonimato não suportado (ASC)
                if tracker_name == "ASC" and meta.get('anon', 'false'):
                    console.print(
                        "PT: [yellow]Aviso: você solicitou upload anônimo, mas o ASC não suporta essa opção.[/yellow]"
                        "[red] O envio não será anônimo.[/red]"
                    )

                # Filtro e confirmação de duplicatas
                if ('skipping' not in local_meta or local_meta['skipping'] is None) and not local_tracker_status['skipped']:
                    dupes = await filter_dupes(dupes, local_meta, tracker_name)
                    meta['we_asked'] = False
                    is_dupe = await helper.dupe_check(dupes, local_meta, tracker_name)
                    if is_dupe:
                        local_tracker_status['dupe'] = True

                    # Repassa “trumpable” do AITHER, se houver
                    if tracker_name == "AITHER" and 'aither_trumpable' in local_meta:
                        meta['aither_trumpable'] = local_meta['aither_trumpable']

                elif 'skipping' in local_meta:
                    local_tracker_status['skipped'] = True

                # Regra especial MTV: tamanho de peça (piece size) do .torrent
                if tracker_name == "MTV":
                    if not local_tracker_status['banned'] and not local_tracker_status['skipped'] and not local_tracker_status['dupe']:
                        tracker_config = config['TRACKERS'].get(tracker_name, {})
                        if str(tracker_config.get('skip_if_rehash', 'false')).lower() == "true":
                            torrent_path = os.path.abspath(f"{local_meta['base_dir']}/tmp/{local_meta['uuid']}/BASE.torrent")
                            if not os.path.exists(torrent_path):
                                check_torrent = await client.find_existing_torrent(local_meta)
                                if check_torrent:
                                    console.print(f"[yellow]Torrent existente encontrado em {check_torrent}[/yellow]")
                                    await create_base_from_existing_torrent(
                                        check_torrent, local_meta['base_dir'], local_meta['uuid']
                                    )
                                    torrent = Torrent.read(torrent_path)
                                    if torrent.piece_size > 8_388_608:
                                        console.print("[yellow]Nenhum torrent existente com piece size menor que 8MB[/yellow]")
                                        local_tracker_status['skipped'] = True
                            elif os.path.exists(torrent_path):
                                torrent = Torrent.read(torrent_path)
                                if torrent.piece_size > 8_388_608:
                                    console.print("[yellow]Torrent existente tem piece size maior que 8MB[/yellow]")
                                    local_tracker_status['skipped'] = True

                we_already_asked = local_meta.get('we_asked', False)

            # Decisão final de upload (assistido/não assistido/debug)
            if not local_meta['debug']:
                if not local_tracker_status['banned'] and not local_tracker_status['skipped'] and not local_tracker_status['dupe']:
                    if not local_meta.get('unattended', False):
                        console.print(f"[bold yellow]Tracker '{tracker_name}' passou em todas as verificações.")
                    if (
                        not local_meta['unattended']
                        or (local_meta['unattended'] and local_meta.get('unattended_confirm', False))
                    ) and not we_already_asked:
                        try:
                            # Alguns trackers podem alterar o nome final
                            try:
                                tracker_rename = await tracker_class.get_name(meta)
                            except Exception:
                                try:
                                    tracker_rename = await tracker_class.edit_name(meta)
                                except Exception:
                                    tracker_rename = None

                            display_name = None
                            if tracker_rename is not None:
                                if isinstance(tracker_rename, dict) and 'name' in tracker_rename:
                                    display_name = tracker_rename['name']
                                elif isinstance(tracker_rename, str):
                                    display_name = tracker_rename

                            if display_name is not None and display_name != "" and display_name != meta['name']:
                                console.print(
                                    f"[bold yellow]{tracker_name} aplicou uma alteração de nome para este release: "
                                    f"[green]{display_name}[/green][/bold yellow]"
                                )

                            # Confirmação do usuário (modo assistido)
                            edit_choice = "y" if local_meta['unattended'] else input(
                                "Digite 'y' para enviar ou pressione Enter para pular o upload:"
                            )
                            if edit_choice.lower() == 'y':
                                local_tracker_status['upload'] = True
                                successful_trackers += 1
                            else:
                                local_tracker_status['upload'] = False
                        except EOFError:
                            console.print("\n[red]Saindo a pedido do usuário (Ctrl+C)[/red]")
                            await cleanup()
                            reset_terminal()
                            sys.exit(1)
                    else:
                        # Não assistido confirmado: sobe direto
                        local_tracker_status['upload'] = True
                        successful_trackers += 1
            else:
                # Modo debug: marcar como “upload” sem realmente enviar
                local_tracker_status['upload'] = True
                successful_trackers += 1

            meta['we_asked'] = False

        return tracker_name, local_tracker_status

    # Execução paralela (quando unattended) ou sequencial
    if meta.get('unattended', False):
        searching_trackers = [name for name in meta['trackers'] if name in tracker_class_map]
        if searching_trackers:
            console.print(f"[yellow]Pesquisando torrents existentes em: {', '.join(searching_trackers)}...")

        tasks = [process_single_tracker(tracker_name, meta) for tracker_name in meta['trackers']]
        results = await asyncio.gather(*tasks)

        # Consolida resultado
        passed_trackers = []
        dupe_trackers = []
        skipped_trackers = []

        for tracker_name, status in results:
            tracker_status[tracker_name] = status
            if not status['banned'] and not status['skipped'] and not status['dupe']:
                passed_trackers.append(tracker_name)
            elif status['dupe']:
                dupe_trackers.append(tracker_name)
            elif status['skipped']:
                skipped_trackers.append(tracker_name)

        if skipped_trackers:
            console.print(f"[red]Trackers pulados devido a condições: [bold yellow]{', '.join(skipped_trackers)}[/bold yellow].")
        if dupe_trackers:
            console.print(f"[red]Encontradas possíveis duplicatas em: [bold yellow]{', '.join(dupe_trackers)}[/bold yellow].")
        if passed_trackers:
            console.print(f"[bold green]Trackers aprovados em todas as verificações: [bold yellow]{', '.join(passed_trackers)}")
    else:
        passed_trackers = []
        for tracker_name in meta['trackers']:
            if tracker_name in tracker_class_map:
                console.print(f"[yellow]Pesquisando torrents existentes em {tracker_name}...")
            tracker_name, status = await process_single_tracker(tracker_name, meta)
            tracker_status[tracker_name] = status
            if not status['banned'] and not status['skipped'] and not status['dupe']:
                passed_trackers.append(tracker_name)

    # Resumo em modo debug
    if meta['debug']:
        console.print("\n[bold]Resumo do processamento por tracker:[/bold]")
        for t_name, status in tracker_status.items():
            banned_status = 'Sim' if status['banned'] else 'Não'
            skipped_status = 'Sim' if status['skipped'] else 'Não'
            dupe_status = 'Sim' if status['dupe'] else 'Não'
            upload_status = 'Sim' if status['upload'] else 'Não'
            console.print(
                f"Tracker: {t_name} | Banido: {banned_status} | Pulado: {skipped_status} | "
                f"Dupe: {dupe_status} | [yellow]Upload:[/yellow] {upload_status}"
            )
        console.print(f"\n[bold]Trackers aprovados em todas as checagens:[/bold] {successful_trackers}")
        print()
        console.print("[bold red]MODO DEBUG não realiza upload aos sites[/bold red]")

    meta['tracker_status'] = tracker_status
    return successful_trackers

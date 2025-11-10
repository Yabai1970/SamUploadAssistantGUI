import cli_ui
import os
import json
import sys

from data.config import config
from src.cleanup import cleanup, reset_terminal
from src.console import console
from src.trackersetup import tracker_class_map


class UploadHelper:
    async def dupe_check(self, dupes, meta, tracker_name):
        if not dupes:
            if meta['debug']:
                console.print(f"[green]Nenhum duplicado encontrado em[/green] [yellow]{tracker_name}[/yellow]")
            return False
        else:
            tracker_class = tracker_class_map[tracker_name](config=config)
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
                console.print(f"[bold yellow]{tracker_name} aplica uma alteração de nome para este lançamento: [green]{display_name}[/green][/bold yellow]")

            if meta.get('trumpable', False):
                trumpable_dupes = [d for d in dupes if isinstance(d, dict) and d.get('trumpable')]
                if trumpable_dupes:
                    trumpable_text = "\n".join([
                        f"{d['name']} - {d['link']}" if 'link' in d else d['name']
                        for d in trumpable_dupes
                    ])
                    console.print("[bold red]Trumpable encontrado![/bold red]")
                    console.print(f"[bold cyan]{trumpable_text}[/bold cyan]")

                    meta['aither_trumpable'] = [
                        {'name': d.get('name'), 'link': d.get('link')}
                        for d in trumpable_dupes
                    ]

                # Remove trumpable dupes from the main list
                dupes = [d for d in dupes if not (isinstance(d, dict) and d.get('trumpable'))]
            if (not meta['unattended'] or (meta['unattended'] and meta.get('unattended_confirm', False))) and not meta.get('ask_dupe', False):
                dupe_text = "\n".join([
                    f"{d['name']} - {d['link']}" if isinstance(d, dict) and 'link' in d and d['link'] is not None else (d['name'] if isinstance(d, dict) else d)
                    for d in dupes
                ])
                if not dupe_text and meta.get('trumpable', False):
                    console.print("[yellow]Verifique as entradas 'trumpable' acima para decidir se deseja enviar e, caso envie, reporte o torrent 'trumpable'.[/yellow]")
                    if meta.get('dupe', False) is False:
                        try:
                            upload = cli_ui.ask_yes_no(f"Upload para {tracker_name} mesmo assim?", default=False)
                            meta['we_asked'] = True
                        except EOFError:
                            console.print("\n[red]Saindo a pedido do usuário (Ctrl+C)[/red]")
                            await cleanup()
                            reset_terminal()
                            sys.exit(1)
                    else:
                        upload = True
                        meta['we_asked'] = False
                else:
                    if meta.get('filename_match', False) and meta.get('file_count_match', False):
                        console.print(f'[bold red]Correspondências exatas de nome de arquivo encontradas! - {meta["filename_match"]}[/bold red]')
                        try:
                            upload = cli_ui.ask_yes_no(f"Upload para {tracker_name} mesmo assim?", default=False)
                            meta['we_asked'] = True
                        except EOFError:
                            console.print("\n[red]Saindo a pedido do usuário (Ctrl+C)[/red]")
                            await cleanup()
                            reset_terminal()
                            sys.exit(1)
                    else:
                        console.print(f"[bold blue]Verifique se estes são realmente duplicados em {tracker_name}:[/bold blue]")
                        console.print()
                        console.print(f"[bold cyan]{dupe_text}[/bold cyan]")
                        if meta.get('dupe', False) is False:
                            try:
                                upload = cli_ui.ask_yes_no(f"Upload para {tracker_name} mesmo assim?", default=False)
                                meta['we_asked'] = True
                            except EOFError:
                                console.print("\n[red]Saindo a pedido do usuário (Ctrl+C)[/red]")
                                await cleanup()
                                reset_terminal()
                                sys.exit(1)
                        else:
                            upload = True
            else:
                if meta.get('dupe', False) is False:
                    upload = False
                else:
                    upload = True

            if upload is False:
                return True
            else:
                for each in dupes:
                    each_name = each['name'] if isinstance(each, dict) else each
                    if each_name == meta['name']:
                        meta['name'] = f"{meta['name']} DUPE?"

                return False

    async def get_confirmation(self, meta):
        if meta['debug'] is True:
            console.print("[bold red]DEBUG: True - Não será feito upload de fato!")
            console.print(f"Material de preparação salvo em {meta['base_dir']}/tmp/{meta['uuid']}")
        console.print()
        console.print("[bold yellow]Informações do Banco de Dados[/bold yellow]")
        console.print(f"[bold]Título:[/bold] {meta['title']} ({meta['year']})")
        console.print()
        if not meta.get('emby', False):
            console.print(f"[bold]Sinopse:[/bold] {meta['overview'][:100]}....")
            console.print()
            if meta.get('category') == 'TV' and not meta.get('tv_pack') and meta.get('auto_episode_title'):
                console.print(f"[bold]Título do episódio:[/bold] {meta['auto_episode_title']}")
                console.print()
            if meta.get('category') == 'TV' and not meta.get('tv_pack') and meta.get('overview_meta'):
                console.print(f"[bold]Sinopse do episódio:[/bold] {meta['overview_meta']}")
                console.print()
            console.print(f"[bold]Gênero:[/bold] {meta['genres']}")
            console.print()
            if str(meta.get('demographic', '')) != '':
                console.print(f"[bold]Demografia:[/bold] {meta['demographic']}")
                console.print()
        console.print(f"[bold]Categoria:[/bold] {meta['category']}")
        console.print()
        if meta.get('emby_debug', False):
            if int(meta.get('original_imdb', 0)) != 0:
                imdb = str(meta.get('original_imdb', 0)).zfill(7)
                console.print(f"[bold]IMDB:[/bold] https://www.imdb.com/title/tt{imdb}")
            if int(meta.get('original_tmdb', 0)) != 0:
                console.print(f"[bold]TMDB:[/bold] https://www.themoviedb.org/{meta['category'].lower()}/{meta['original_tmdb']}")
            if int(meta.get('original_tvdb', 0)) != 0:
                console.print(f"[bold]TVDB:[/bold] https://www.thetvdb.com/?id={meta['original_tvdb']}&tab=series")
            if int(meta.get('original_tvmaze', 0)) != 0:
                console.print(f"[bold]TVMaze:[/bold] https://www.tvmaze.com/shows/{meta['original_tvmaze']}")
            if int(meta.get('original_mal', 0)) != 0:
                console.print(f"[bold]MAL:[/bold] https://myanimelist.net/anime/{meta['original_mal']}")
        else:
            if int(meta.get('tmdb_id') or 0) != 0:
                console.print(f"[bold]TMDB:[/bold] https://www.themoviedb.org/{meta['category'].lower()}/{meta['tmdb_id']}")
            if int(meta.get('imdb_id') or 0) != 0:
                console.print(f"[bold]IMDB:[/bold] https://www.imdb.com/title/tt{meta['imdb']}")
            if int(meta.get('tvdb_id') or 0) != 0:
                console.print(f"[bold]TVDB:[/bold] https://www.thetvdb.com/?id={meta['tvdb_id']}&tab=series")
            if int(meta.get('tvmaze_id') or 0) != 0:
                console.print(f"[bold]TVMaze:[/bold] https://www.tvmaze.com/shows/{meta['tvmaze_id']}")
            if int(meta.get('mal_id') or 0) != 0:
                console.print(f"[bold]MAL:[/bold] https://myanimelist.net/anime/{meta['mal_id']}")
        console.print()
        if not meta.get('emby', False):
            if int(meta.get('freeleech', 0)) != 0:
                console.print(f"[bold]Freeleech:[/bold] {meta['freeleech']}")

            info_parts = []
            info_parts.append(meta['source'] if meta['is_disc'] == 'DVD' else meta['resolution'])
            info_parts.append(meta['type'])
            if meta.get('tag', ''):
                info_parts.append(meta['tag'][1:])
            if meta.get('region', ''):
                info_parts.append(meta['region'])
            if meta.get('distributor', ''):
                info_parts.append(meta['distributor'])
            console.print(' / '.join(info_parts))

            if meta.get('personalrelease', False) is True:
                console.print("[bold green]Lançamento pessoal![/bold green]")
            console.print()

        if meta.get('unattended', False) and not meta.get('unattended_confirm', False) and not meta.get('emby_debug', False):
            if meta['debug'] is True:
                console.print("[bold yellow]Modo não assistido habilitado; pulando confirmação.[/bold yellow]")
            return True
        else:
            if not meta.get('emby', False):
                await self.get_missing(meta)
                ring_the_bell = "\a" if config['DEFAULT'].get("sfx_on_prompt", True) is True else ""
                if ring_the_bell:
                    console.print(ring_the_bell)

            if meta.get('is disc', False) is True:
                meta['keep_folder'] = False

            if meta.get('keep_folder') and meta['isdir']:
                kf_confirm = console.input("[bold yellow]Você especificou --keep-folder. Upload em pastas pode não ser permitido.[/bold yellow] [green]Prosseguir? y/N: [/green]").strip().lower()
                if kf_confirm != 'y':
                    console.print("[bold red]Abortando...[/bold red]")
                    exit()

            if not meta.get('emby', False):
                console.print(f"[bold]Nome:[/bold] {meta['name']}")
                confirm = console.input("[bold green]Está correto?[/bold green] [yellow]y/N[/yellow]: ").strip().lower() == 'y'
            elif not meta.get('emby_debug', False):
                confirm = console.input("[bold green]Está correto?[/bold green] [yellow]y/N[/yellow]: ").strip().lower() == 'y'
        if meta.get('emby_debug', False):
            if meta.get('original_imdb', 0) != meta.get('imdb_id', 0):
                imdb = str(meta.get('imdb_id', 0)).zfill(7)
                console.print(f"[bold red]IMDB ID alterado de {meta['original_imdb']} para {meta['imdb_id']}[/bold red]")
                console.print(f"[bold cyan]URL do IMDB:[/bold cyan] [yellow]https://www.imdb.com/title/tt{imdb}[/yellow]")
            if meta.get('original_tmdb', 0) != meta.get('tmdb_id', 0):
                console.print(f"[bold red]TMDB ID alterado de {meta['original_tmdb']} para {meta['tmdb_id']}[/bold red]")
                console.print(f"[bold cyan]URL do TMDB:[/bold cyan] [yellow]https://www.themoviedb.org/{meta['category'].lower()}/{meta['tmdb_id']}[/yellow]")
            if meta.get('original_mal', 0) != meta.get('mal_id', 0):
                console.print(f"[bold red]MAL ID alterado de {meta['original_mal']} para {meta['mal_id']}[/bold red]")
                console.print(f"[bold cyan]URL do MAL:[/bold cyan] [yellow]https://myanimelist.net/anime/{meta['mal_id']}[/yellow]")
            if meta.get('original_tvmaze', 0) != meta.get('tvmaze_id', 0):
                console.print(f"[bold red]TVMaze ID alterado de {meta['original_tvmaze']} para {meta['tvmaze_id']}[/bold red]")
                console.print(f"[bold cyan]URL do TVMaze:[/bold cyan] [yellow]https://www.tvmaze.com/shows/{meta['tvmaze_id']}[/yellow]")
            if meta.get('original_tvdb', 0) != meta.get('tvdb_id', 0):
                console.print(f"[bold red]TVDB ID alterado de {meta['original_tvdb']} para {meta['tvdb_id']}[/bold red]")
                console.print(f"[bold cyan]URL do TVDB:[/bold cyan] [yellow]https://www.thetvdb.com/?id={meta['tvdb_id']}&tab=series[/yellow]")
            if meta.get('original_category', None) != meta.get('category', None):
                console.print(f"[bold red]Categoria alterada de {meta['original_category']} para {meta['category']}[/bold red]")
            console.print(f"[bold cyan]Título (regex):[/bold cyan] [yellow]{meta.get('regex_title', 'N/A')}[/yellow], [bold cyan]Título secundário:[/bold cyan] [yellow]{meta.get('regex_secondary_title', 'N/A')}[/yellow], [bold cyan]Ano:[/bold cyan] [yellow]{meta.get('regex_year', 'N/A')}, [bold cyan]AKA:[/bold cyan] [yellow]{meta.get('aka', '')}[/yellow]")
            console.print()
            if meta.get('original_imdb', 0) == meta.get('imdb_id', 0) and meta.get('original_tmdb', 0) == meta.get('tmdb_id', 0) and meta.get('original_mal', 0) == meta.get('mal_id', 0) and meta.get('original_tvmaze', 0) == meta.get('tvmaze_id', 0) and meta.get('original_tvdb', 0) == meta.get('tvdb_id', 0) and meta.get('original_category', None) == meta.get('category', None):
                console.print("[bold yellow]IDs de banco de dados estão corretos![/bold yellow]")
                return True
            else:
                nfo_dir = os.path.join(f"{meta['base_dir']}/data")
                os.makedirs(nfo_dir, exist_ok=True)
                json_file_path = os.path.join(nfo_dir, "db_check.json")

                def imdb_url(imdb_id):
                    return f"https://www.imdb.com/title/tt{str(imdb_id).zfill(7)}" if imdb_id and str(imdb_id).isdigit() else None

                def tmdb_url(tmdb_id, category):
                    return f"https://www.themoviedb.org/{str(category).lower()}/{tmdb_id}" if tmdb_id and category else None

                def tvdb_url(tvdb_id):
                    return f"https://www.thetvdb.com/?id={tvdb_id}&tab=series" if tvdb_id else None

                def tvmaze_url(tvmaze_id):
                    return f"https://www.tvmaze.com/shows/{tvmaze_id}" if tvmaze_id else None

                def mal_url(mal_id):
                    return f"https://myanimelist.net/anime/{mal_id}" if mal_id else None

                db_check_entry = {
                    "path": meta.get('path'),
                    "original": {
                        "imdb_id": meta.get('original_imdb', 'N/A'),
                        "imdb_url": imdb_url(meta.get('original_imdb')),
                        "tmdb_id": meta.get('original_tmdb', 'N/A'),
                        "tmdb_url": tmdb_url(meta.get('original_tmdb'), meta.get('original_category')),
                        "tvdb_id": meta.get('original_tvdb', 'N/A'),
                        "tvdb_url": tvdb_url(meta.get('original_tvdb')),
                        "tvmaze_id": meta.get('original_tvmaze', 'N/A'),
                        "tvmaze_url": tvmaze_url(meta.get('original_tvmaze')),
                        "mal_id": meta.get('original_mal', 'N/A'),
                        "mal_url": mal_url(meta.get('original_mal')),
                        "category": meta.get('original_category', 'N/A')
                    },
                    "changed": {
                        "imdb_id": meta.get('imdb_id', 'N/A'),
                        "imdb_url": imdb_url(meta.get('imdb_id')),
                        "tmdb_id": meta.get('tmdb_id', 'N/A'),
                        "tmdb_url": tmdb_url(meta.get('tmdb_id'), meta.get('category')),
                        "tvdb_id": meta.get('tvdb_id', 'N/A'),
                        "tvdb_url": tvdb_url(meta.get('tvdb_id')),
                        "tvmaze_id": meta.get('tvmaze_id', 'N/A'),
                        "tvmaze_url": tvmaze_url(meta.get('tvmaze_id')),
                        "mal_id": meta.get('mal_id', 'N/A'),
                        "mal_url": mal_url(meta.get('mal_id')),
                        "category": meta.get('category', 'N/A')
                    },
                    "tracker": meta.get('matched_tracker', 'N/A'),
                }

                # Append to JSON file (as a list of entries)
                if os.path.exists(json_file_path):
                    with open(json_file_path, 'r', encoding='utf-8') as f:
                        try:
                            db_data = json.load(f)
                            if not isinstance(db_data, list):
                                db_data = []
                        except Exception:
                            db_data = []
                else:
                    db_data = []

                db_data.append(db_check_entry)

                with open(json_file_path, 'w', encoding='utf-8') as f:
                    json.dump(db_data, f, indent=2, ensure_ascii=False)
                return True

        return confirm

    async def get_missing(self, meta):
        info_notes = {
            'edition': 'Special Edition/Release',
            'description': "Please include Remux/Encode Notes if possible",
            'service': "WEB Service e.g.(AMZN, NF)",
            'region': "Disc Region",
            'imdb': 'IMDb ID (tt1234567)',
            'distributor': "Disc Distributor e.g.(BFI, Criterion)"
        }
        missing = []
        if meta.get('imdb_id', 0) == 0:
            meta['imdb_id'] = 0
            meta['potential_missing'].append('imdb_id')
        for each in meta['potential_missing']:
            if str(meta.get(each, '')).strip() in ["", "None", "0"]:
                missing.append(f"--{each} | {info_notes.get(each, '')}")
        if missing:
            console.print("[bold yellow]Informações potencialmente ausentes:[/bold yellow]")
            for each in missing:
                cli_ui.info(each)

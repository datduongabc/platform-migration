import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { ChatMessage, ChatService } from '../../services/chat.service';
import { Folder, FolderService } from '../../services/folder.service';
import { ChatComponent } from './chat';

function makeFolder(id: string, name: string): Folder {
  return {
    id,
    user_id: 'user-1',
    name,
    position: 0,
    created_at: '2026-07-27T00:00:00Z',
    updated_at: '2026-07-27T00:00:00Z',
    myRole: 'owner',
    ownerUsername: 'someuser',
    memberCount: 1,
  };
}

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    session_id: 'session-1',
    role: 'assistant',
    content: 'hi',
    citations: [],
    created_at: '2026-07-27T00:00:00Z',
    ...overrides,
  };
}

describe('ChatComponent — folder scope picker', () => {
  let component: ChatComponent;
  let chatService: { getHistory: ReturnType<typeof vi.fn>; sendQuery: ReturnType<typeof vi.fn> };
  let folderService: { listFolders: ReturnType<typeof vi.fn> };

  function setup() {
    chatService = {
      getHistory: vi.fn().mockReturnValue(of({ sessionId: 'session-1', messages: [] })),
      sendQuery: vi.fn().mockReturnValue(
        of({ sessionId: 'session-1', message: makeMessage() }),
      ),
    };
    folderService = {
      listFolders: vi.fn().mockReturnValue(
        of({ folders: [makeFolder('folder-1', 'Work'), makeFolder('folder-2', 'Personal')] }),
      ),
    };

    TestBed.configureTestingModule({
      imports: [ChatComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ChatService, useValue: chatService },
        { provide: FolderService, useValue: folderService },
      ],
    });

    const fixture = TestBed.createComponent(ChatComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the folder list and history scoped to global on init', () => {
    setup();

    expect(component.folders()).toEqual([
      expect.objectContaining({ id: 'folder-1', name: 'Work' }),
      expect.objectContaining({ id: 'folder-2', name: 'Personal' }),
    ]);
    expect(chatService.getHistory).toHaveBeenCalledWith(null, null);
  });

  it('onScopeChange resets the session and reloads history scoped to the selected folder', () => {
    setup();
    component.sessionId.set('old-session');
    component.messages.set([makeMessage()]);
    component.selectedFolderId = 'folder-1';

    component.onScopeChange();

    expect(component.messages()).toEqual([]);
    expect(chatService.getHistory).toHaveBeenLastCalledWith(null, 'folder-1');
  });

  it('sendMessage passes the currently selected folder scope through to the backend', () => {
    setup();
    component.selectedFolderId = 'folder-2';
    component.sessionId.set('session-1');
    component.chatQuery = 'What was discussed?';

    component.sendMessage();

    expect(chatService.sendQuery).toHaveBeenCalledWith(
      'What was discussed?',
      null,
      'session-1',
      'folder-2',
    );
  });

  it('sendMessage passes null scope when global (no folder selected)', () => {
    setup();
    component.selectedFolderId = '';
    component.chatQuery = 'hello';

    component.sendMessage();

    expect(chatService.sendQuery).toHaveBeenCalledWith('hello', null, expect.anything(), null);
  });
});
